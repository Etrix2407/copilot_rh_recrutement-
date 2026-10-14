"""Droit à l'effacement (RGPD) : un candidat supprimé disparaît de toutes les données de l'application."""

import logging

from app.services.agent_chat import ConversationStore
from app.services.candidate_store import CandidateStore

logger = logging.getLogger(__name__)


def erase_candidate(candidate_id: str, *, store: CandidateStore, conversations: ConversationStore) -> None:
    """Supprime le candidat, son analyse et les conversations de l'agent qui le mentionnent.

    Lève CandidateNotFoundError si l'identifiant est inconnu.
    """
    candidate = store.get(candidate_id)
    store.delete(candidate_id)
    # Les conversations contiennent son nom et son email (demandes, arguments des outils)
    forgotten = conversations.forget_mentions([candidate.name, candidate.email or ""])
    logger.info("Candidat effacé, %d conversation(s) oubliée(s)", forgotten)
