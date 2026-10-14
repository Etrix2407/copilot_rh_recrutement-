"""Adaptateur Gemini : seul module autorisé à importer le SDK google-genai."""

from collections.abc import Sequence

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from app.llm.base import LLMError, Message, Role, ToolCall, ToolDefinition

# Gemini nomme « model » le rôle de l'assistant ; les résultats d'outils sont envoyés par « user »
_GEMINI_ROLES = {Role.USER: "user", Role.ASSISTANT: "model", Role.TOOL: "user"}

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
        http_options = types.HttpOptions(
            retry_options=TRANSIENT_ERROR_RETRY,
            # Un transport httpx explicite empêche le SDK de basculer sur aiohttp dès qu'il est installé
            # (ChromaDB l'installe) : ses erreurs réseau échapperaient alors à la conversion en LLMError.
            async_client_args={"transport": transport or httpx.AsyncHTTPTransport()},
        )
        self._client = genai.Client(api_key=api_key, http_options=http_options)
        self._model = model

    async def aclose(self) -> None:
        await self._client.aio.aclose()

    async def generate(self, prompt: str) -> str:
        return _text_of(await self._generate(contents=prompt, config=None), self._model)

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
        response = await self._generate(contents=_to_contents(messages), config=config)
        return _text_of(response, self._model)

    async def generate_with_tools(
        self,
        messages: Sequence[Message],
        *,
        system: str,
        tools: Sequence[ToolDefinition],
        temperature: float,
    ) -> Message:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=tool.name,
                            description=tool.description,
                            parameters_json_schema=tool.parameters,
                        )
                        for tool in tools
                    ]
                )
            ],
            # Les outils sont exécutés par notre boucle d'agent, jamais par le SDK
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = await self._generate(contents=_to_contents(messages), config=config)
        return _to_message(response, self._model)

    async def _generate(
        self,
        *,
        contents: str | list[types.Content],
        config: types.GenerateContentConfig | None,
    ) -> types.GenerateContentResponse:
        try:
            return await self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )
        except errors.APIError as exc:
            raise LLMError(f"Appel à Gemini ({self._model}) échoué : {exc}") from exc
        # Le SDK laisse passer les erreurs réseau (connexion, timeout) de son client httpx
        except httpx.HTTPError as exc:
            raise LLMError(f"Gemini ({self._model}) injoignable : {exc}") from exc


def _text_of(response: types.GenerateContentResponse, model: str) -> str:
    # text vaut None si la réponse a été bloquée ou ne contient pas de texte
    if not response.text:
        raise LLMError(f"Gemini ({model}) a renvoyé une réponse vide.")
    return response.text


def _to_contents(messages: Sequence[Message]) -> list[types.Content]:
    return [types.Content(role=_GEMINI_ROLES[message.role], parts=_to_parts(message)) for message in messages]


def _to_parts(message: Message) -> list[types.Part]:
    parts = [types.Part.from_text(text=message.content)] if message.content else []
    parts += [
        types.Part(
            function_call=types.FunctionCall(id=call.id, name=call.name, args=call.arguments),
            thought_signature=call.signature,
        )
        for call in message.tool_calls
    ]
    parts += [
        types.Part(
            function_response=types.FunctionResponse(
                id=result.call_id,
                name=result.name,
                # Gemini attend un objet JSON : les autres valeurs (une liste de créneaux…) sont enveloppées
                response=result.content if isinstance(result.content, dict) else {"result": result.content},
            )
        )
        for result in message.tool_results
    ]
    return parts


def _to_message(response: types.GenerateContentResponse, model: str) -> Message:
    content = response.candidates[0].content if response.candidates else None
    parts = (content.parts if content else None) or []
    # Les parties « thought » sont le raisonnement interne du modèle, pas la réponse
    text = "".join(part.text for part in parts if part.text and not part.thought)
    tool_calls = [
        ToolCall(
            id=part.function_call.id,
            name=part.function_call.name or "",
            arguments=part.function_call.args or {},
            signature=part.thought_signature,
        )
        for part in parts
        if part.function_call
    ]
    if not text and not tool_calls:
        raise LLMError(f"Gemini ({model}) a renvoyé une réponse vide.")
    return Message(role=Role.ASSISTANT, content=text, tool_calls=tool_calls)
