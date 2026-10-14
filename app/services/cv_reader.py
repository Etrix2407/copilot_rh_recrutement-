"""Obtention du texte d'un CV : fichier envoyé (PDF ou texte) ou texte collé."""

import io
import multiprocessing
import os
import threading
import time
from multiprocessing.connection import Connection
from pathlib import PurePath

import pdfplumber

# Limites contre les fichiers démesurés (mémoire, temps de traitement, quota du LLM)
MAX_CV_BYTES = 2_000_000
MAX_PDF_PAGES = 10
MAX_CV_CHARS = 30_000
# Un petit PDF peut cacher des millions d'opérations de dessin (« bombe » de complexité) :
# l'extraction tourne dans un processus séparé, arrêté de force au-delà de ce délai
PDF_TIMEOUT_SECONDS = 10.0
# Mémoire maximale du processus d'extraction (« bombe » de décompression : 2 Mo qui deviennent 600 Mo)
PDF_MAX_MEMORY_BYTES = 400_000_000
# Extractions simultanées au maximum : un afflux de PDF n'occupe pas toute la machine
MAX_PARALLEL_PDF = 2

PDF_UNREADABLE = "Fichier PDF illisible, corrompu ou trop lourd à traiter."

_pdf_slots = threading.BoundedSemaphore(MAX_PARALLEL_PDF)


class CVReadError(Exception):
    """Impossible d'obtenir le texte du CV. Le message est destiné à l'utilisateur."""


class CVReaderBusyError(Exception):
    """Trop d'extractions de PDF en cours : la demande est refusée tout de suite au lieu d'attendre."""

    def __init__(self) -> None:
        super().__init__("Trop d'analyses de PDF en cours. Réessayez dans quelques secondes.")


SUPPORTED_SUFFIXES = (".pdf", ".txt")
# Caractères qui s'affichent comme un blanc sans être des espaces au sens de Python
_BLANK_LOOKALIKES = frozenset({"⠀", "ㅤ", "ﾠ", "ᅟ", "ᅠ"})


def check_cv_request(*, filename: str | None, has_file: bool, has_text: bool) -> None:
    """Contrôles immédiats, avant toute lecture : un fichier OU un texte, et un format pris en charge.

    Lève CVReadError ; permet de refuser une demande invalide sans consommer le quota.
    """
    if has_file == has_text:
        raise CVReadError("Envoyez soit un fichier, soit du texte.")
    if has_file and PurePath(filename or "").suffix.lower() not in SUPPORTED_SUFFIXES:
        raise CVReadError("Format non pris en charge : envoyez un fichier .pdf ou .txt.")


def extract_cv_text(*, filename: str | None, content: bytes | None, text: str | None) -> str:
    """Renvoie le texte du CV, venant soit d'un fichier (nom + contenu), soit d'un texte collé.

    Fonction synchrone et coûteuse pour un PDF : à appeler hors de la boucle d'événements.
    Lève CVReadError avec un message destiné à l'utilisateur.
    """
    if (content is None) == (text is None):
        raise CVReadError("Envoyez soit un fichier, soit du texte.")
    if content is not None:
        cv_text = read_cv_file(filename or "", content)
    else:
        cv_text = text or ""
        if not _visible_text(cv_text):
            raise CVReadError("Le texte du CV est vide.")
    if len(cv_text) > MAX_CV_CHARS:
        raise CVReadError(f"CV trop long : {MAX_CV_CHARS} caractères maximum.")
    return cv_text


def read_cv_file(filename: str, content: bytes) -> str:
    """Renvoie le texte du CV contenu dans un fichier .pdf ou .txt."""
    if len(content) > MAX_CV_BYTES:
        raise CVReadError(f"Fichier trop volumineux : {MAX_CV_BYTES // 1_000_000} Mo maximum.")
    match PurePath(filename).suffix.lower():
        case ".pdf":
            text = _extract_pdf_text(content)
        case ".txt":
            text = _decode_text(content)
        case _:
            raise CVReadError("Format non pris en charge : envoyez un fichier .pdf ou .txt.")

    if not _visible_text(text):
        raise CVReadError(
            "Le fichier ne contient aucun texte extractible (PDF scanné ?). Collez le texte du CV à la place."
        )
    return text


def _extract_pdf_text(content: bytes) -> str:
    """Extrait le texte dans un processus séparé, tué s'il dépasse PDF_TIMEOUT_SECONDS."""
    context = multiprocessing.get_context("spawn")
    # Sans attente : un afflux de PDF ne bloque pas les threads partagés avec le reste de l'API
    if not _pdf_slots.acquire(blocking=False):
        raise CVReaderBusyError
    try:
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(
            target=_extract_in_child, args=(content, MAX_PDF_PAGES, PDF_MAX_MEMORY_BYTES, sender), daemon=True
        )
        process.start()
        sender.close()
        try:
            if not receiver.poll(PDF_TIMEOUT_SECONDS):
                raise CVReadError("PDF trop complexe à lire. Collez le texte du CV à la place.")
            ok, value = receiver.recv()
        except EOFError as exc:
            # Le processus est mort sans répondre (mémoire épuisée, plantage de la bibliothèque)
            raise CVReadError(PDF_UNREADABLE) from exc
        finally:
            process.kill()
            process.join()
            receiver.close()
    finally:
        _pdf_slots.release()
    if not ok:
        raise CVReadError(value)
    return value


def _extract_in_child(content: bytes, max_pages: int, max_memory: int, sender: Connection) -> None:
    """Exécuté dans le processus séparé : renvoie (True, texte) ou (False, message d'erreur)."""
    _limit_child_memory(max_memory)
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            if len(pdf.pages) > max_pages:
                sender.send((False, f"CV trop long : {max_pages} pages maximum."))
                return
            sender.send((True, "\n".join(page.extract_text() or "" for page in pdf.pages)))
    # Un PDF malformé lève des exceptions de types très variés selon la bibliothèque concernée
    except Exception:
        sender.send((False, PDF_UNREADABLE))
    finally:
        sender.close()


def _limit_child_memory(max_memory: int) -> None:
    """Borne la mémoire du processus d'extraction : un petit PDF peut se décompresser en centaines de Mo.

    Sous Linux/macOS, le système refuse toute allocation au-delà de la limite. Windows n'offre pas
    d'équivalent simple : un fil de surveillance arrête le processus dès que sa mémoire dépasse la limite.
    Dans les deux cas, le processus parent reçoit une fin de flux et répond « PDF illisible ».
    """
    try:
        import resource  # absent sous Windows
    except ImportError:
        threading.Thread(target=_watch_memory_windows, args=(max_memory,), daemon=True).start()
        return
    resource.setrlimit(resource.RLIMIT_AS, (max_memory, max_memory))


def _watch_memory_windows(max_memory: int) -> None:
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    # Types déclarés : sans eux, la poignée de processus 64 bits serait tronquée (erreur « handle invalide »)
    get_current_process = ctypes.windll.kernel32.GetCurrentProcess
    get_current_process.restype = wintypes.HANDLE
    get_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
    get_memory_info.restype = wintypes.BOOL

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    process = get_current_process()
    while True:
        if not get_memory_info(process, ctypes.byref(counters), counters.cb):
            return  # mesure impossible : seul le délai maximal protège alors
        # PagefileUsage : mémoire privée engagée par le processus
        if counters.PagefileUsage > max_memory:
            os._exit(1)
        time.sleep(0.05)


def _visible_text(text: str) -> str:
    """Texte sans espaces ni caractères invisibles (espaces de largeur nulle, caractères de contrôle…)."""
    return "".join(
        char for char in text if char.isprintable() and not char.isspace() and char not in _BLANK_LOOKALIKES
    )


def _decode_text(content: bytes) -> str:
    try:
        # utf-8-sig : le BOM éventuel (fichiers enregistrés par le Bloc-notes) n'est pas envoyé au LLM
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CVReadError("Le fichier texte doit être encodé en UTF-8.") from exc
