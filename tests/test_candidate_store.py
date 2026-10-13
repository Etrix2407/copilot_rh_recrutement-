import pytest

from app.models.candidate import CandidateStatus
from app.services.candidate_store import (
    CandidateNotFoundError,
    CandidateStore,
    InvalidStatusTransitionError,
)


def test_new_candidate_starts_with_new_status() -> None:
    store = CandidateStore()

    candidate = store.add(name="Jean Dupont", email="jean.dupont@email.com")

    assert candidate.status is CandidateStatus.NEW
    assert store.get(candidate.id) == candidate
    assert store.list_all() == [candidate]


def test_full_happy_path_is_allowed() -> None:
    store = CandidateStore()
    candidate = store.add(name="Jean Dupont", email=None)

    for status in (CandidateStatus.ANALYZED, CandidateStatus.INTERVIEW_SCHEDULED, CandidateStatus.ACCEPTED):
        candidate = store.update_status(candidate.id, status)

    assert store.get(candidate.id).status is CandidateStatus.ACCEPTED


def test_skipping_a_step_is_rejected() -> None:
    store = CandidateStore()
    candidate = store.add(name="Sophie Martin", email=None)

    with pytest.raises(InvalidStatusTransitionError):
        store.update_status(candidate.id, CandidateStatus.ACCEPTED)

    assert store.get(candidate.id).status is CandidateStatus.NEW


def test_unknown_candidate_raises_not_found() -> None:
    with pytest.raises(CandidateNotFoundError):
        CandidateStore().get("unknown")
