import asyncio

import httpx
import pytest
from google.genai import types
from google.genai.models import AsyncModels

from app.llm import gemini
from app.llm.base import LLMError
from app.llm.gemini import GeminiClient

GEMINI_OK_RESPONSE = {"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}}]}
GEMINI_OVERLOADED_RESPONSE = {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}}


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mêmes règles de relance, sans attendre plusieurs secondes entre deux essais
    fast = gemini.TRANSIENT_ERROR_RETRY.model_copy(update={"initial_delay": 0.01, "max_delay": 0.01, "jitter": 0.0})
    monkeypatch.setattr(gemini, "TRANSIENT_ERROR_RETRY", fast)


def gemini_server(statuses: list[int]) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    """Simule Gemini : répond avec les codes HTTP donnés, dans l'ordre."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        status = statuses[len(requests) - 1]
        return httpx.Response(status, json=GEMINI_OK_RESPONSE if status == 200 else GEMINI_OVERLOADED_RESPONSE)

    return httpx.MockTransport(handler), requests


def test_overloaded_model_is_retried() -> None:
    transport, requests = gemini_server([503, 503, 200])
    client = GeminiClient(api_key="fake-key", model="test-model", transport=transport)

    assert asyncio.run(client.generate("Bonjour")) == "ok"
    assert len(requests) == 3


def test_persistent_overload_becomes_llm_error() -> None:
    transport, requests = gemini_server([503, 503, 503])
    client = GeminiClient(api_key="fake-key", model="test-model", transport=transport)

    with pytest.raises(LLMError, match="503"):
        asyncio.run(client.generate("Bonjour"))
    assert len(requests) == gemini.TRANSIENT_ERROR_RETRY.attempts


def test_client_error_is_not_retried() -> None:
    transport, requests = gemini_server([400])
    client = GeminiClient(api_key="fake-key", model="test-model", transport=transport)

    with pytest.raises(LLMError):
        asyncio.run(client.generate("Bonjour"))
    assert len(requests) == 1


def test_network_error_becomes_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unreachable(*args: object, **kwargs: object) -> types.GenerateContentResponse:
        raise httpx.ConnectError("All connection attempts failed")

    # On remplace l'appel réseau du SDK : aucun appel réel à Gemini
    monkeypatch.setattr(AsyncModels, "generate_content", unreachable)
    client = GeminiClient(api_key="fake-key", model="test-model")

    with pytest.raises(LLMError, match="injoignable"):
        asyncio.run(client.generate("Bonjour"))
