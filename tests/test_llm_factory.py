import asyncio

from app.config import Settings
from app.llm.factory import create_llm_client
from app.llm.gemini import GeminiClient


def test_gemini_provider_builds_gemini_client(test_settings: Settings) -> None:
    client = create_llm_client(test_settings)

    try:
        assert isinstance(client, GeminiClient)
    finally:
        asyncio.run(client.aclose())
