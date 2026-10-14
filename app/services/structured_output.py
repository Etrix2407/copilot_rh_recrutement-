"""Appel au LLM avec une réponse JSON validée par Pydantic, et une relance si elle est invalide."""

import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.llm.base import LLMClient, Message, Role

logger = logging.getLogger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

# 1 appel + 1 relance si la réponse ne respecte pas le schéma
MAX_ATTEMPTS = 2


class InvalidLLMOutputError(Exception):
    """Le LLM n'a pas produit de réponse conforme au schéma dans le nombre d'appels autorisé."""


async def generate_validated(
    llm: LLMClient,
    prompt: str,
    *,
    system: str,
    schema: type[SchemaT],
    temperature: float,
) -> SchemaT:
    """Renvoie la réponse du LLM validée par le schéma.

    Si la réponse est invalide, l'erreur de validation est renvoyée au LLM pour une seule relance.
    Lève InvalidLLMOutputError, ou LLMError si l'appel lui-même échoue.
    """
    messages = [Message(role=Role.USER, content=prompt)]
    last_error: ValidationError | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        raw_answer = await llm.generate_json(messages, system=system, schema=schema, temperature=temperature)
        try:
            return schema.model_validate_json(raw_answer)
        except ValidationError as exc:
            # Seul le nombre d'erreurs est journalisé : le détail peut contenir des données personnelles
            logger.warning(
                "Réponse %s invalide (appel %d/%d) : %d erreur(s) de schéma",
                schema.__name__,
                attempt,
                MAX_ATTEMPTS,
                exc.error_count(),
            )
            last_error = exc
            if attempt == MAX_ATTEMPTS:
                break
            messages += [
                Message(role=Role.ASSISTANT, content=raw_answer),
                Message(
                    role=Role.USER,
                    content=(
                        f"Ta réponse ne respecte pas le schéma attendu :\n{exc}\n"
                        "Renvoie la réponse complète corrigée."
                    ),
                ),
            ]

    raise InvalidLLMOutputError(
        f"Le LLM n'a pas produit de réponse valide après {MAX_ATTEMPTS} appels."
    ) from last_error
