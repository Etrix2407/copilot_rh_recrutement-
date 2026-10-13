"""Adaptateur Gemini : seul module autorisé à importer le SDK google-genai."""

from collections.abc import Sequence

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from app.llm.base import LLMError, Message, Role

# Gemini nomme « model » le rôle de l'assistant
_GEMINI_ROLES = {Role.USER: "user", Role.ASSISTANT: "model"}

# Relances réseau faites par le SDK, uniquement pour les erreurs temporaires :
# 503 (modèle surchargé) et 429 (quota par minute dépassé), avec un délai croissant.
# Elles sont indépendantes des relances du parsing, qui concernent les réponses invalides.
TRANSIENT_ERROR_RETRY = types.HttpRetryOptions(
    attempts=3,
    initial_delay=2.0,
    max_delay=10.0,
    http_status_codes=[429, 503],
)


class GeminiClient:
    def __init__(self, *, api_key: str, model: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """transport permet aux tests de simuler les réponses HTTP de Gemini sans réseau."""
        http_options = types.HttpOptions(retry_options=TRANSIENT_ERROR_RETRY)
        if transport is not None:
            http_options.async_client_args = {"transport": transport}
        self._client = genai.Client(api_key=api_key, http_options=http_options)
        self._model = model

    async def generate(self, prompt: str) -> str:
        return await self._generate_text(contents=prompt, config=None)

    async def generate_json(
        self,
        messages: Sequence[Message],
        *,
        system: str,
        schema: type[BaseModel],
        temperature: float,
    ) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema(),
        )
        contents = [
            types.Content(role=_GEMINI_ROLES[message.role], parts=[types.Part.from_text(text=message.content)])
            for message in messages
        ]
        return await self._generate_text(contents=contents, config=config)

    async def _generate_text(
        self,
        *,
        contents: str | list[types.Content],
        config: types.GenerateContentConfig | None,
    ) -> str:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
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
