from collections.abc import Callable

import pytest

from app.services.cv_reader import CVReadError, read_cv_file


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
