from app.config import Settings
from app.llm.factory import create_llm_client
from app.llm.gemini import GeminiClient


def test_gemini_provider_builds_gemini_client() -> None:
    # _env_file=None : le test ne dépend pas du .env local
    settings = Settings(llm_provider="gemini", llm_model="test-model", llm_api_key="fake-key", _env_file=None)

    client = create_llm_client(settings)

    assert isinstance(client, GeminiClient)
