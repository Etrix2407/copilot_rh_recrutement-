import pytest

from app.models.candidate import Candidate, CandidateStatus
from app.services.candidate_store import CandidateStore
from app.tools.candidates import update_candidate_status


@pytest.fixture
def store() -> CandidateStore:
    return CandidateStore()


@pytest.fixture
def analyzed_candidate(store: CandidateStore) -> Candidate:
    candidate = store.add(name="Jean Dupont", email="jean.dupont@email.com")
    return store.update_status(candidate.id, CandidateStatus.ANALYZED)


def test_updates_status_by_id(store: CandidateStore, analyzed_candidate: Candidate) -> None:
    result = update_candidate_status(store, analyzed_candidate.id, "interview_scheduled")

    assert result["statut"] == "SUCCES"
    assert store.get(analyzed_candidate.id).status is CandidateStatus.INTERVIEW_SCHEDULED


def test_updates_status_by_name_ignoring_case(store: CandidateStore, analyzed_candidate: Candidate) -> None:
    result = update_candidate_status(store, "  jean DUPONT ", "interview_scheduled")

    assert result["statut"] == "SUCCES"
    assert store.get(analyzed_candidate.id).status is CandidateStatus.INTERVIEW_SCHEDULED


def test_refuses_forbidden_transition(store: CandidateStore, analyzed_candidate: Candidate) -> None:
    result = update_candidate_status(store, analyzed_candidate.id, "accepted")

    assert result["statut"] == "ERREUR"
    assert "interdit" in result["message"]
    assert store.get(analyzed_candidate.id).status is CandidateStatus.ANALYZED


def test_refuses_unknown_status(store: CandidateStore, analyzed_candidate: Candidate) -> None:
    result = update_candidate_status(store, analyzed_candidate.id, "hired")

    assert result["statut"] == "ERREUR"
    assert "interview_scheduled" in result["message"]


def test_reports_unknown_candidate(store: CandidateStore) -> None:
    result = update_candidate_status(store, "Paul Inconnu", "analyzed")

    assert result == {"statut": "ERREUR", "message": "Aucun candidat trouvé pour 'Paul Inconnu'."}


def test_refuses_ambiguous_name(store: CandidateStore) -> None:
    store.add(name="Jean Dupont", email=None)
    store.add(name="Jean Dupont", email=None)

    result = update_candidate_status(store, "Jean Dupont", "analyzed")

    assert result["statut"] == "ERREUR"
    assert "Plusieurs candidats" in result["message"]
