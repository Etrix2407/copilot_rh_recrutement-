"""Extraction du texte d'un CV envoyé sous forme de fichier (PDF ou texte)."""

import io
from pathlib import PurePath

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException


class CVReadError(Exception):
    """Le fichier ne permet pas d'obtenir le texte du CV. Le message est destiné à l'utilisateur."""


def read_cv_file(filename: str, content: bytes) -> str:
    """Renvoie le texte du CV contenu dans un fichier .pdf ou .txt."""
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
    return text


def _extract_pdf_text(content: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except PdfminerException as exc:
        raise CVReadError("Fichier PDF illisible ou corrompu.") from exc


def _decode_text(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CVReadError("Le fichier texte doit être encodé en UTF-8.") from exc
