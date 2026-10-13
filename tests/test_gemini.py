import asyncio

import httpx
import pytest
from google.genai.models import AsyncModels

from app.llm.base import LLMError
from app.llm.gemini import GeminiClient


def test_network_error_becomes_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unreachable(*args: object, **kwargs: object) -> None:
        raise httpx.ConnectError("All connection attempts failed")

    # On remplace l'appel réseau du SDK : aucun appel réel à Gemini
    monkeypatch.setattr(AsyncModels, "generate_content", unreachable)
    client = GeminiClient(api_key="fake-key", model="test-model")

    with pytest.raises(LLMError, match="injoignable"):
        asyncio.run(client.generate("Bonjour"))
