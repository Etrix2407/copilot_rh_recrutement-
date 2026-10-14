import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.dependencies import CandidateStoreDep
from app.models.interview import InterviewSlots
from app.services.candidate_store import CandidateNotFoundError
from app.services.interviews import free_slots_for

router = APIRouter(prefix="/api/interviews", tags=["interviews"])


@router.get("/slots")
async def list_slots(
    store: CandidateStoreDep,
    candidate_id: Annotated[str, Query(description="Identifiant du candidat")],
    date: Annotated[datetime.date, Query(description="Date au format YYYY-MM-DD")],
) -> InterviewSlots:
    """Renvoie les créneaux d'entretien libres à une date, pour un candidat existant."""
    try:
        return free_slots_for(candidate_id, date, store=store)
    except CandidateNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
