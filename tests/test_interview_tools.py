import pytest

from app.data.agenda import RECRUITER_AGENDA
from app.tools.interviews import book_interview, search_interview_slots


def test_search_returns_free_slots_of_known_date() -> None:
    assert search_interview_slots("2026-10-15") == ["09:00", "11:00", "14:30", "16:00"]


def test_search_returns_empty_list_for_date_without_slots() -> None:
    assert search_interview_slots("2026-12-25") == []


@pytest.mark.usefixtures("restore_agenda")
def test_booking_removes_slot_from_agenda() -> None:
    result = book_interview("Jean Dupont", "2026-10-15", "09:00", "jean.dupont@email.com")

    assert result == {
        "statut": "SUCCES",
        "message": "Entretien confirmé pour Jean Dupont le 2026-10-15 à 09:00. Invitation envoyée à jean.dupont@email.com.",
    }
    assert search_interview_slots("2026-10-15") == ["11:00", "14:30", "16:00"]


@pytest.mark.usefixtures("restore_agenda")
def test_booking_same_slot_twice_fails_the_second_time() -> None:
    book_interview("Jean Dupont", "2026-10-15", "09:00", "jean.dupont@email.com")

    result = book_interview("Sophie Martin", "2026-10-15", "09:00", "sophie.martin@email.com")

    assert result == {"statut": "ERREUR", "message": "Créneau indisponible."}


@pytest.mark.parametrize(("date", "time"), [("2026-12-25", "09:00"), ("2026-10-15", "08:00")])
def test_booking_unknown_slot_fails_without_touching_agenda(date: str, time: str) -> None:
    before = {day: list(times) for day, times in RECRUITER_AGENDA.items()}

    result = book_interview("Jean Dupont", date, time, "jean.dupont@email.com")

    assert result["statut"] == "ERREUR"
    assert RECRUITER_AGENDA == before
