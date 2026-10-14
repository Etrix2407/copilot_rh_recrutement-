import threading
from collections.abc import Callable

import pytest

from app.services import cv_reader
from app.services.cv_reader import CVReaderBusyError, CVReadError, extract_cv_text, read_cv_file


def test_pdf_text_is_extracted(make_pdf: Callable[[str], bytes]) -> None:
    text = read_cv_file("cv.pdf", make_pdf("Jean Dupont - Python FastAPI"))

    assert "Jean Dupont - Python FastAPI" in text


def test_pdf_without_text_is_rejected(make_pdf: Callable[[str], bytes]) -> None:
    with pytest.raises(CVReadError, match="aucun texte"):
        read_cv_file("scan.pdf", make_pdf(""))


def test_corrupted_pdf_is_rejected() -> None:
    with pytest.raises(CVReadError, match="illisible"):
        read_cv_file("cv.pdf", b"ceci n'est pas un PDF")


def test_text_file_is_decoded() -> None:
    assert read_cv_file("cv.TXT", "Développeuse Python".encode()) == "Développeuse Python"


def test_non_utf8_text_file_is_rejected() -> None:
    with pytest.raises(CVReadError, match="UTF-8"):
        read_cv_file("cv.txt", "Développeuse".encode("utf-16"))


def test_unsupported_format_is_rejected() -> None:
    with pytest.raises(CVReadError, match="Format non pris en charge"):
        read_cv_file("cv.docx", b"...")


def test_pdf_with_too_many_pages_is_rejected(monkeypatch: pytest.MonkeyPatch, make_pdf: Callable[[str], bytes]) -> None:
    monkeypatch.setattr(cv_reader, "MAX_PDF_PAGES", 0)

    with pytest.raises(CVReadError, match="pages maximum"):
        read_cv_file("cv.pdf", make_pdf("Jean Dupont"))


def test_too_long_text_file_is_rejected() -> None:
    with pytest.raises(CVReadError, match="trop long"):
        extract_cv_text(filename="cv.txt", content=b"x" * (cv_reader.MAX_CV_CHARS + 1), text=None)


def test_utf8_bom_is_not_kept() -> None:
    assert read_cv_file("cv.txt", "﻿Jean Dupont".encode()) == "Jean Dupont"


def test_malformed_pdf_is_rejected_cleanly(make_pdf: Callable[[str], bytes]) -> None:
    # MediaBox absente : pdfplumber lève une TypeError, pas une erreur PDF
    pdf = make_pdf("Jean").replace(b"/MediaBox [0 0 612 792]", b"/MediaBox null         ")

    with pytest.raises(CVReadError, match="illisible"):
        read_cv_file("cv.pdf", pdf)


def test_too_complex_pdf_is_stopped(monkeypatch: pytest.MonkeyPatch, make_pdf: Callable[[str], bytes]) -> None:
    # Délai nul : le processus d'extraction est arrêté avant d'avoir répondu
    monkeypatch.setattr(cv_reader, "PDF_TIMEOUT_SECONDS", 0)

    with pytest.raises(CVReadError, match="trop complexe"):
        read_cv_file("cv.pdf", make_pdf("Jean Dupont"))


@pytest.mark.parametrize(
    ("content", "text"),
    [(None, None), (b"Jean", "Jean")],
    ids=["aucun", "les_deux"],
)
def test_file_or_text_but_not_both(content: bytes | None, text: str | None) -> None:
    with pytest.raises(CVReadError, match="soit un fichier, soit du texte"):
        extract_cv_text(filename="cv.txt", content=content, text=text)


def test_blank_pasted_text_is_rejected() -> None:
    with pytest.raises(CVReadError, match="vide"):
        extract_cv_text(filename=None, content=None, text="   ")


def test_too_large_file_is_rejected() -> None:
    with pytest.raises(CVReadError, match="trop volumineux"):
        read_cv_file("cv.txt", b"x" * (cv_reader.MAX_CV_BYTES + 1))


def test_invisible_text_is_rejected() -> None:
    with pytest.raises(CVReadError, match="vide"):
        extract_cv_text(filename=None, content=None, text="\u200b\u200b \n")


def test_pdf_extraction_refuses_instead_of_waiting_when_busy(
    monkeypatch: pytest.MonkeyPatch, make_pdf: Callable[[str], bytes]
) -> None:
    # Aucune place libre : la demande est refusée tout de suite
    monkeypatch.setattr(cv_reader, "_pdf_slots", threading.BoundedSemaphore(1))
    cv_reader._pdf_slots.acquire()

    with pytest.raises(CVReaderBusyError):
        read_cv_file("cv.pdf", make_pdf("Jean Dupont"))
