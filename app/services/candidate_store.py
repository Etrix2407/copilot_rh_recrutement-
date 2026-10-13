"""Stockage des candidats en mémoire : il est vidé à chaque redémarrage de l'API."""

import uuid

from app.models.candidate import Candidate, CandidateStatus

# Parcours d'un candidat : nouveau → analysé → entretien planifié → retenu / refusé.
# Un candidat analysé peut aussi être refusé sans entretien.
ALLOWED_TRANSITIONS: dict[CandidateStatus, frozenset[CandidateStatus]] = {
    CandidateStatus.NEW: frozenset({CandidateStatus.ANALYZED}),
    CandidateStatus.ANALYZED: frozenset({CandidateStatus.INTERVIEW_SCHEDULED, CandidateStatus.REJECTED}),
    CandidateStatus.INTERVIEW_SCHEDULED: frozenset({CandidateStatus.ACCEPTED, CandidateStatus.REJECTED}),
    CandidateStatus.ACCEPTED: frozenset(),
    CandidateStatus.REJECTED: frozenset(),
}


class CandidateNotFoundError(Exception):
    def __init__(self, candidate_id: str) -> None:
        super().__init__(f"Aucun candidat avec l'identifiant {candidate_id!r}.")
        self.candidate_id = candidate_id


class InvalidStatusTransitionError(Exception):
    def __init__(self, current: CandidateStatus, target: CandidateStatus) -> None:
        super().__init__(f"Passage du statut {current.value!r} à {target.value!r} interdit.")
        self.current = current
        self.target = target


class CandidateStore:
    def __init__(self) -> None:
        self._candidates: dict[str, Candidate] = {}

    def add(self, *, name: str, email: str | None) -> Candidate:
        candidate = Candidate(id=uuid.uuid4().hex, name=name, email=email)
        self._candidates[candidate.id] = candidate
        return candidate

    def get(self, candidate_id: str) -> Candidate:
        try:
            return self._candidates[candidate_id]
        except KeyError:
            raise CandidateNotFoundError(candidate_id) from None

    def list_all(self) -> list[Candidate]:
        return list(self._candidates.values())

    def update_status(self, candidate_id: str, status: CandidateStatus) -> Candidate:
        candidate = self.get(candidate_id)
        if status not in ALLOWED_TRANSITIONS[candidate.status]:
            raise InvalidStatusTransitionError(candidate.status, status)
        updated = candidate.model_copy(update={"status": status})
        self._candidates[candidate_id] = updated
        return updated
