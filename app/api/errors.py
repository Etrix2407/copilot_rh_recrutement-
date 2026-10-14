"""Erreurs communes aux routes."""

import logging

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# Message générique : le détail de l'erreur du fournisseur (modèle, réponse brute) reste dans les logs
LLM_UNAVAILABLE = "Le service d'IA est momentanément indisponible. Réessayez dans quelques instants."


def llm_unavailable(exc: Exception) -> HTTPException:
    """Journalise l'échec du LLM et renvoie une erreur 502 sans détail interne."""
    logger.warning("Échec de l'appel au LLM : %s", exc)
    return HTTPException(status.HTTP_502_BAD_GATEWAY, LLM_UNAVAILABLE)
