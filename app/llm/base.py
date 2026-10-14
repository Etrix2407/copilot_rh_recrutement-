"""Port LLM : l'interface que le reste de l'application utilise, quel que soit le fournisseur."""

from collections.abc import AsyncIterator, Sequence
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class LLMError(Exception):
    """Échec d'un appel au fournisseur de LLM (réseau, quota, clé invalide, réponse vide…)."""


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    # Résultats des outils exécutés par l'application, renvoyés au LLM
    TOOL = "tool"


class ToolCall(BaseModel):
    """Appel d'outil demandé par le LLM."""

    model_config = ConfigDict(frozen=True)

    # Identifiant donné par le fournisseur (peut manquer), repris dans le résultat
    id: str | None = None
    name: str
    arguments: dict[str, Any]
    # Donnée opaque propre au fournisseur, à lui renvoyer telle quelle avec l'appel
    # (Gemini refuse un historique d'appels d'outils sans leur « thought signature »)
    signature: bytes | None = None


class ToolResult(BaseModel):
    """Résultat d'un outil exécuté par l'application, en réponse à un ToolCall."""

    model_config = ConfigDict(frozen=True)

    call_id: str | None = None
    name: str
    content: Any


class Message(BaseModel):
    """Un message de l'historique de conversation envoyé au LLM.

    Selon le rôle : texte de l'utilisateur, texte et/ou appels d'outils de
    l'assistant, ou résultats des outils.
    """

    model_config = ConfigDict(frozen=True)

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = []
    tool_results: list[ToolResult] = []


class ToolDefinition(BaseModel):
    """Description d'un outil pour le LLM, indépendante du fournisseur."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    # Paramètres au format JSON Schema (type « object »)
    parameters: dict[str, Any]


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

    def stream_with_tools(
        self,
        messages: Sequence[Message],
        *,
        system: str,
        tools: Sequence[ToolDefinition],
        temperature: float,
    ) -> AsyncIterator[str | Message]:
        """Produit la réponse de l'assistant au fil de l'eau.

        Produit d'abord les morceaux de texte dès qu'ils arrivent, puis, en dernier,
        le Message complet (texte entier et/ou outils que le LLM veut appeler).
        Les outils ne sont jamais exécutés ici : c'est à l'appelant de le faire
        et de renvoyer leurs résultats dans un message de rôle TOOL.
        Lève LLMError si l'appel échoue.
        """
        ...

    async def aclose(self) -> None:
        """Ferme les connexions réseau ouvertes par le client."""
        ...
