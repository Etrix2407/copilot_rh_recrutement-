"""Adaptateur Gemini : seul module autorisé à importer le SDK google-genai."""

import httpx
from google import genai
from google.genai import errors

from app.llm.base import LLMError


class GeminiClient:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def generate(self, prompt: str) -> str:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
            )
        except errors.APIError as exc:
            raise LLMError(f"Appel à Gemini ({self._model}) échoué : {exc}") from exc
        # Le SDK laisse passer les erreurs réseau (connexion, timeout) de son client httpx
        except httpx.HTTPError as exc:
            raise LLMError(f"Gemini ({self._model}) injoignable : {exc}") from exc

        # text vaut None si la réponse a été bloquée ou ne contient pas de texte
        if not response.text:
            raise LLMError(f"Gemini ({self._model}) a renvoyé une réponse vide.")
        return response.text
