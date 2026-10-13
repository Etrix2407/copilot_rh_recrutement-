from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class CandidateStatus(StrEnum):
    NEW = "new"
    ANALYZED = "analyzed"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Candidate(BaseModel):
    """Candidat suivi par l'application.

    L'analyse du CV (compétences, score…) sera ajoutée avec le pilier 1.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    # Un CV ne contient pas toujours d'email
    email: str | None
    status: CandidateStatus = CandidateStatus.NEW
