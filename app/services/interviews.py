"""Consultation des créneaux d'entretien pour un candidat (endpoint GET /api/interviews/slots)."""

import datetime

from app.models.interview import InterviewSlots
from app.services.candidate_store import CandidateStore
from app.tools.interviews import search_interview_slots


def free_slots_for(candidate_id: str, date: datetime.date, *, store: CandidateStore) -> InterviewSlots:
    """Renvoie les créneaux libres à cette date, pour un candidat existant.

    Lève CandidateNotFoundError si le candidat est inconnu : un identifiant inventé
    ne reçoit pas de réponse valide.
    """
    store.get(candidate_id)
    # Copie : la réponse ne doit pas partager la liste de l'agenda, modifiée par les réservations
    return InterviewSlots(date=date, slots=list(search_interview_slots(date.isoformat())))
