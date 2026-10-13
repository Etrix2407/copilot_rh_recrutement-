"""Port LLM : l'interface que le reste de l'application utilise, quel que soit le fournisseur."""

from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class LLMError(Exception):
    """Échec d'un appel au fournisseur de LLM (réseau, quota, clé invalide, réponse vide…)."""


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    """Un message de l'historique de conversation envoyé au LLM."""

    model_config = ConfigDict(frozen=True)

    role: Role
    content: str


class LLMClient(Protocol):
    async def generate(self, prompt: str) -> str:
        """Envoie un prompt et renvoie la réponse texte complète.

        Lève LLMError si l'appel échoue.
        """
        ...

    async def generate_json(
        self,
        messages: Sequence[Message],
        *,
        system: str,
        schema: type[BaseModel],
        temperature: float,
    ) -> str:
        """Renvoie le JSON brut produit par le modèle, contraint par le schéma.

        La validation reste à la charge de l'appelant : le fournisseur peut
        renvoyer un JSON qui ne respecte pas toutes les contraintes du schéma.
        Lève LLMError si l'appel échoue.
        """
        ...

    async def aclose(self) -> None:
        """Ferme les connexions réseau ouvertes par le client."""
        ...
