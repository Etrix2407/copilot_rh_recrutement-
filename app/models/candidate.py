from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.models.cv_analysis import CVAnalysis


class CandidateStatus(StrEnum):
    NEW = "new"
    ANALYZED = "analyzed"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Candidate(BaseModel):
    """Candidat suivi par l'application."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    # Un CV ne contient pas toujours d'email
    email: str | None
    status: CandidateStatus = CandidateStatus.NEW
    # Renseignée quand le candidat passe au statut « analysé »
    analysis: CVAnalysis | None = None
