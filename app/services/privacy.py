"""Droit à l'effacement (RGPD) : un candidat supprimé disparaît de toutes les données de l'application."""

import logging

from app.services.agent_chat import ConversationStore
from app.services.candidate_store import CandidateStore

logger = logging.getLogger(__name__)


def erase_candidate(candidate_id: str, *, store: CandidateStore, conversations: ConversationStore) -> None:
    """Supprime le candidat, son analyse et TOUTES les conversations de l'agent en mémoire.

    Chercher le candidat dans les conversations ne suffirait pas : « M. Dupont », « DUPONT Jean »
    ou une faute de frappe échapperaient à la recherche. Toutes les conversations sont donc
    oubliées, et une réponse de l'agent en cours n'enregistrera pas la sienne (voir
    ConversationStore.save). Lève CandidateNotFoundError si l'identifiant est inconnu.
    """
    store.delete(candidate_id)
    forgotten = conversations.forget_all()
    logger.info("Candidat effacé, %d conversation(s) oubliée(s)", forgotten)
