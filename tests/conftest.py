import json
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_llm_client
from app.config import Settings
from app.main import create_app
from tests.fakes import FakeLLMClient, build_pdf


@pytest.fixture
def test_settings() -> Settings:
    # _env_file=None : les tests ne lisent jamais le .env local ni la vraie clé
    return Settings(llm_provider="gemini", llm_model="test-model", llm_api_key="fake-key", _env_file=None)


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def client(test_settings: Settings, fake_llm: FakeLLMClient) -> Iterator[TestClient]:
    app = create_app(test_settings)
    # Les routes reçoivent le faux LLM : aucun appel réseau pendant les tests
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    # Le bloc with déclenche le démarrage (lifespan) de l'application
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def valid_analysis_json() -> str:
    return json.dumps(
        {
            "candidate_name": "Jean Dupont",
            "email": "jean.dupont@email.com",
            "key_skills": ["Python", "FastAPI", "RAG"],
            "years_of_experience": 6,
            "education_level": "bac+5",
            "match_score": 90,
            "score_justifications": ["6 ans d'expérience pour 5 requis."],
            "red_flags": [],
        }
    )


@pytest.fixture
def make_pdf() -> Callable[[str], bytes]:
    return build_pdf
