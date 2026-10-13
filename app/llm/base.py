"""Port LLM : l'interface que le reste de l'application utilise, quel que soit le fournisseur."""

from typing import Protocol


class LLMError(Exception):
    """Échec d'un appel au fournisseur de LLM (réseau, quota, clé invalide, réponse vide…)."""


class LLMClient(Protocol):
    async def generate(self, prompt: str) -> str:
        """Envoie un prompt et renvoie la réponse texte complète.

        Lève LLMError si l'appel échoue.
        """
        ...
