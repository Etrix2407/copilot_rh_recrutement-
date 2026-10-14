import unicodedata

import pytest

from app.models.candidate import Candidate, CandidateStatus
from app.services.candidate_store import CandidateStore
from app.tools.candidates import AmbiguousCandidateError, find_candidate, normalize_name, update_candidate_status


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
    assert "précisez l'email" in result["message"]


def test_email_resolves_homonyms(store: CandidateStore) -> None:
    other = store.add(name="Jean Dupont", email="autre.jean@email.com")
    jean = store.add(name="Jean Dupont", email="jean.dupont@email.com")
    store.update_status(jean.id, CandidateStatus.ANALYZED)

    result = update_candidate_status(store, "JEAN.DUPONT@email.com", "rejected")

    assert result["statut"] == "SUCCES"
    assert store.get(jean.id).status is CandidateStatus.REJECTED
    assert store.get(other.id).status is not CandidateStatus.REJECTED


def test_email_shared_by_several_candidates_is_ambiguous(store: CandidateStore) -> None:
    alice = store.add(name="Alice Martin", email="contact@famille.fr")
    bob = store.add(name="Bob Martin", email="contact@famille.fr")
    for candidate in (alice, bob):
        store.update_status(candidate.id, CandidateStatus.ANALYZED)

    result = update_candidate_status(store, "contact@famille.fr", "rejected")

    assert result["statut"] == "ERREUR"
    assert "précisez le nom ou l'identifiant" in result["message"]
    assert store.get(bob.id).status is CandidateStatus.ANALYZED


def test_shared_email_does_not_block_lookup_by_id(store: CandidateStore) -> None:
    store.add(name="Alice Martin", email="contact@famille.fr")
    bob = store.add(name="Bob Martin", email="contact@famille.fr")

    assert find_candidate(store, bob.id) == bob
    with pytest.raises(AmbiguousCandidateError):
        find_candidate(store, "contact@famille.fr")


def test_normalize_name_ignores_unicode_form() -> None:
    # Un nom extrait d'un PDF peut être en forme décomposée (NFD)
    decomposed = unicodedata.normalize("NFD", "Hélène Faure")

    assert decomposed != "Hélène Faure"
    assert normalize_name(decomposed) == normalize_name("Hélène Faure")


def test_decomposed_name_finds_the_candidate(store: CandidateStore) -> None:
    helene = store.add(name="Hélène Faure", email=None)

    assert find_candidate(store, unicodedata.normalize("NFD", "hélène faure")) == helene
