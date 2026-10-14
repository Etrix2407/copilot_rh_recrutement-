import logging

import pytest

from app.data.agenda import RECRUITER_AGENDA
from app.llm.base import ToolCall
from app.models.candidate import CandidateStatus
from app.services.agent_tools import FOLLOW_UP_KEY, run_tool
from app.services.candidate_store import CandidateNotFoundError, CandidateStore, InvalidStatusTransitionError

JEAN = {"candidat_nom": "Jean Dupont", "date": "2026-10-15", "heure": "09:00", "email": "jean.dupont@email.com"}
SEARCHED = {"2026-10-15"}


@pytest.fixture
def store() -> CandidateStore:
    return CandidateStore()


def run(store: CandidateStore, name: str, **arguments: object) -> object:
    call = ToolCall(id="1", name=name, arguments=arguments)
    return run_tool(call, store=store, searched_dates=SEARCHED).content


def book(store: CandidateStore, **changes: object) -> dict[str, str]:
    return run(store, "reserver_entretien", **{**JEAN, **changes})


def analyzed(store: CandidateStore, name: str, email: str | None) -> str:
    candidate = store.add(name=name, email=email)
    return store.update_status(candidate.id, CandidateStatus.ANALYZED).id


# --- Noms d'arguments : ceux du cahier des charges, vus par le LLM ---


def test_english_argument_names_are_refused(store: CandidateStore) -> None:
    result = run(
        store,
        "reserver_entretien",
        candidate_name="Jean Dupont",
        date="2026-10-15",
        time="09:00",
        email="jean.dupont@email.com",
    )

    assert result["statut"] == "ERREUR"
    assert "09:00" in RECRUITER_AGENDA["2026-10-15"]


def test_status_tool_refuses_english_argument_names(store: CandidateStore) -> None:
    candidate = analyzed(store, "Jean Dupont", None)

    result = run(store, "mettre_a_jour_statut_candidat", candidate="Jean Dupont", status="rejected")

    assert result["statut"] == "ERREUR"
    assert store.get(candidate).status is CandidateStatus.ANALYZED


def test_invalid_argument_message_uses_llm_names(store: CandidateStore) -> None:
    result = book(store, heure="9h")

    assert result == {"statut": "ERREUR", "message": "Arguments invalides : heure."}


def test_missing_argument_message_uses_llm_names(store: CandidateStore) -> None:
    result = run(store, "reserver_entretien", date="2026-10-15", email="jean.dupont@email.com")

    assert result == {"statut": "ERREUR", "message": "Arguments invalides : candidat_nom, heure."}


# --- Rapprochement du nom et de l'email avant de réserver ---


def test_email_of_another_candidate_is_refused(store: CandidateStore) -> None:
    analyzed(store, "Sophie Martin", "jean.dupont@email.com")

    result = book(store)

    assert result["statut"] == "ERREUR"
    assert "nom et l'email" in result["message"]
    assert "09:00" in RECRUITER_AGENDA["2026-10-15"]


def test_name_matching_ignores_spaces_and_case(store: CandidateStore) -> None:
    candidate = analyzed(store, "Jean Dupont", "jean.dupont@email.com")

    result = book(store, candidat_nom="  jean   DUPONT ")

    assert result["statut"] == "SUCCES"
    assert store.get(candidate).status is CandidateStatus.INTERVIEW_SCHEDULED


def test_name_with_another_email_is_refused(store: CandidateStore) -> None:
    analyzed(store, "Jean Dupont", "autre.jean@email.com")

    result = book(store)

    assert result["statut"] == "ERREUR"
    assert "09:00" in RECRUITER_AGENDA["2026-10-15"]


def test_ambiguous_name_without_matching_email_asks_for_email(store: CandidateStore) -> None:
    analyzed(store, "Jean Dupont", None)
    analyzed(store, "Jean Dupont", None)

    result = book(store)

    assert result["statut"] == "ERREUR"
    assert "email" in result["message"]
    assert "09:00" in RECRUITER_AGENDA["2026-10-15"]


def test_name_without_email_on_file_is_scheduled(store: CandidateStore) -> None:
    candidate = analyzed(store, "Jean Dupont", None)

    result = book(store)

    assert result["statut"] == "SUCCES"
    assert store.get(candidate).status is CandidateStatus.INTERVIEW_SCHEDULED


def test_unknown_candidate_can_still_be_booked(store: CandidateStore) -> None:
    result = book(store)

    assert result["statut"] == "SUCCES"
    assert "Aucun dossier" in result[FOLLOW_UP_KEY]


# --- Réservation non atomique : le dossier change entre la vérification et la mise à jour ---


@pytest.mark.parametrize(
    "error",
    [
        CandidateNotFoundError("id"),
        InvalidStatusTransitionError(CandidateStatus.REJECTED, CandidateStatus.INTERVIEW_SCHEDULED),
    ],
    ids=["dossier_supprime", "statut_change"],
)
def test_booking_stays_valid_when_candidate_changes_meanwhile(
    store: CandidateStore, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    analyzed(store, "Jean Dupont", "jean.dupont@email.com")

    def changed_meanwhile(candidate_id: str, status: CandidateStatus) -> None:
        raise error

    monkeypatch.setattr(store, "update_status", changed_meanwhile)

    with caplog.at_level(logging.WARNING, logger="app.services.agent_tools"):
        result = book(store)

    assert result["statut"] == "SUCCES"
    assert "non mis à jour" in result[FOLLOW_UP_KEY]
    assert "09:00" not in RECRUITER_AGENDA["2026-10-15"]
    assert [record.levelno for record in caplog.records] == [logging.WARNING]
    assert "Jean Dupont" not in caplog.text and "jean.dupont@email.com" not in caplog.text
