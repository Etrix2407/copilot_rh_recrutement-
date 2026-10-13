"""Exécution des appels au vrai LLM dans les tests marqués llm."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.config import get_settings
from app.llm.base import LLMClient
from app.llm.factory import create_llm_client

ResultT = TypeVar("ResultT")


def run_with_real_llm(call: Callable[[LLMClient], Awaitable[ResultT]]) -> ResultT:
    """Crée un client avec le .env, exécute l'appel puis ferme le client.

    Tout se passe dans la même boucle asyncio : un client ne peut pas être
    réutilisé après la fin de l'asyncio.run qui l'a vu naître.
    """

    async def run() -> ResultT:
        llm = create_llm_client(get_settings())
        try:
            return await call(llm)
        finally:
            await llm.aclose()

    return asyncio.run(run())
