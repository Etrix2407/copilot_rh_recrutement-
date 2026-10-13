"""Choisit l'adaptateur LLM à partir de la configuration."""

from typing import assert_never

from app.config import Settings
from app.llm.base import LLMClient
from app.llm.gemini import GeminiClient


def create_llm_client(settings: Settings) -> LLMClient:
    match settings.llm_provider:
        case "gemini":
            return GeminiClient(
                api_key=settings.llm_api_key.get_secret_value(),
                model=settings.llm_model,
            )
        case _:
            assert_never(settings.llm_provider)
