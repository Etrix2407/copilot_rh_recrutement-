from pathlib import Path

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


def test_candidates_survive_a_restart(tmp_path: Path) -> None:
    path = str(tmp_path / "candidates.db")
    store = CandidateStore(path)
    candidate = store.add(name="Jean Dupont", email="jean.dupont@email.com")
    store.update_status(candidate.id, CandidateStatus.ANALYZED)
    store.close()

    reopened = CandidateStore(path)

    assert reopened.get(candidate.id).status is CandidateStatus.ANALYZED
    reopened.close()


def test_list_keeps_insertion_order() -> None:
    store = CandidateStore()
    names = ["Zoé", "Adam", "Marc"]
    for name in names:
        store.add(name=name, email=None)

    assert [candidate.name for candidate in store.list_all()] == names


def test_delete_removes_candidate() -> None:
    store = CandidateStore()
    candidate = store.add(name="Jean Dupont", email=None)

    store.delete(candidate.id)

    with pytest.raises(CandidateNotFoundError):
        store.get(candidate.id)
    assert store.list_all() == []


def test_delete_unknown_candidate_fails() -> None:
    with pytest.raises(CandidateNotFoundError):
        CandidateStore().delete("unknown")
