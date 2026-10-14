"""Extraction du texte d'un CV envoyé sous forme de fichier (PDF ou texte)."""

import io
from pathlib import PurePath

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException

# Limites contre les fichiers démesurés (mémoire, temps de traitement, quota du LLM)
MAX_CV_BYTES = 2_000_000
MAX_PDF_PAGES = 10
MAX_CV_CHARS = 30_000


class CVReadError(Exception):
    """Le fichier ne permet pas d'obtenir le texte du CV. Le message est destiné à l'utilisateur."""


def read_cv_file(filename: str, content: bytes) -> str:
    """Renvoie le texte du CV contenu dans un fichier .pdf ou .txt.

    Fonction synchrone et coûteuse pour un PDF : à appeler hors de la boucle d'événements.
    """
    if len(content) > MAX_CV_BYTES:
        raise CVReadError(f"Fichier trop volumineux : {MAX_CV_BYTES // 1_000_000} Mo maximum.")
    match PurePath(filename).suffix.lower():
        case ".pdf":
            text = _extract_pdf_text(content)
        case ".txt":
            text = _decode_text(content)
        case _:
            raise CVReadError("Format non pris en charge : envoyez un fichier .pdf ou .txt.")

    if not text.strip():
        raise CVReadError(
            "Le fichier ne contient aucun texte extractible (PDF scanné ?). Collez le texte du CV à la place."
        )
    check_cv_length(text)
    return text


def check_cv_length(text: str) -> None:
    """Refuse un CV trop long : au-delà, ce n'est plus un CV et l'appel au LLM coûterait cher."""
    if len(text) > MAX_CV_CHARS:
        raise CVReadError(f"CV trop long : {MAX_CV_CHARS} caractères maximum.")


def _extract_pdf_text(content: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            if len(pdf.pages) > MAX_PDF_PAGES:
                raise CVReadError(f"CV trop long : {MAX_PDF_PAGES} pages maximum.")
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except PdfminerException as exc:
        raise CVReadError("Fichier PDF illisible ou corrompu.") from exc


def _decode_text(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CVReadError("Le fichier texte doit être encodé en UTF-8.") from exc
