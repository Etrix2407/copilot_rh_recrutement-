"""Garantit que les données et les outils d'entretien sont conformes au cahier des charges."""

import copy
from collections.abc import Callable

import pytest

from app.data.agenda import RECRUITER_AGENDA
from app.data.candidates import SAMPLE_CANDIDATE_1, SAMPLE_CANDIDATE_2
from app.data.hr_policies import HR_POLICIES
from app.data.job_offers import PYTHON_DEV_JOB_OFFER
from app.tools.interviews import book_interview, search_interview_slots


@pytest.mark.parametrize(
    ("spec_name", "project_value"),
    [
        ("POLITIQUES_RH", HR_POLICIES),
        ("OFFRE_POSTE_DEV_PYTHON", PYTHON_DEV_JOB_OFFER),
        ("CANDIDAT_EXEMPLE_1", SAMPLE_CANDIDATE_1),
        ("CANDIDAT_EXEMPLE_2", SAMPLE_CANDIDATE_2),
        ("AGENDA_RECRUTEUR", RECRUITER_AGENDA),
    ],
)
def test_data_matches_spec(spec_namespace: dict[str, object], spec_name: str, project_value: object) -> None:
    assert project_value == spec_namespace[spec_name]


@pytest.mark.parametrize(
    ("spec_name", "project_tool"),
    [("rechercher_creneaux_entretien", search_interview_slots), ("reserver_entretien", book_interview)],
)
def test_interview_tools_keep_spec_docstrings(
    spec_namespace: dict[str, object], spec_name: str, project_tool: Callable[..., object]
) -> None:
    spec_tool = spec_namespace[spec_name]

    assert project_tool.__doc__ == spec_tool.__doc__


@pytest.fixture
def spec_agenda(spec_namespace: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Remplace l'agenda du cahier par une copie, rétablie après le test (celui du projet l'est par restore_agenda)."""
    agenda = copy.deepcopy(spec_namespace["AGENDA_RECRUTEUR"])
    monkeypatch.setitem(spec_namespace, "AGENDA_RECRUTEUR", agenda)
    return agenda


@pytest.mark.parametrize("date", ["2026-10-15", "2026-10-16", "2026-12-25"])
def test_search_behaves_like_spec(
    spec_namespace: dict[str, object], spec_agenda: dict[str, list[str]], date: str
) -> None:
    spec_search = spec_namespace["rechercher_creneaux_entretien"]

    assert search_interview_slots(date) == spec_search(date)


# Suites de réservations : réussie, créneau déjà pris, date inconnue, heure inconnue
BOOKING_SCENARIOS = [
    [("Jean Dupont", "2026-10-15", "09:00", "jean.dupont@email.com")],
    [
        ("Jean Dupont", "2026-10-15", "09:00", "jean.dupont@email.com"),
        ("Sophie Martin", "2026-10-15", "09:00", "sophie.martin@email.com"),
    ],
    [("Jean Dupont", "2026-12-25", "09:00", "jean.dupont@email.com")],
    [("Jean Dupont", "2026-10-15", "08:00", "jean.dupont@email.com")],
]


@pytest.mark.parametrize("bookings", BOOKING_SCENARIOS)
def test_booking_behaves_like_spec(
    spec_namespace: dict[str, object],
    spec_agenda: dict[str, list[str]],
    bookings: list[tuple[str, str, str, str]],
) -> None:
    spec_book = spec_namespace["reserver_entretien"]

    for arguments in bookings:
        assert book_interview(*arguments) == spec_book(*arguments)
    # Même effet sur l'agenda (restore_agenda remet celui du projet à zéro après le test)
    assert RECRUITER_AGENDA == spec_agenda
