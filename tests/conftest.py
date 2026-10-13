from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def test_settings() -> Settings:
    # _env_file=None : les tests ne lisent jamais le .env local ni la vraie clé
    return Settings(llm_provider="gemini", llm_model="test-model", llm_api_key="fake-key", _env_file=None)


@pytest.fixture
def client(test_settings: Settings) -> Iterator[TestClient]:
    # Le bloc with déclenche le démarrage (lifespan) de l'application
    with TestClient(create_app(test_settings)) as test_client:
        yield test_client
