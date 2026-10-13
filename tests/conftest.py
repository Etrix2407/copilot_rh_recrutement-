import json
from collections.abc import Callable, Iterator
from pathlib import Path

import chromadb
import pytest
from chromadb.config import Settings as ChromaSettings
from fastapi.testclient import TestClient

from app.api.dependencies import get_llm_client
from app.config import Settings
from app.main import create_app
from app.services.policy_index import PolicyIndex
from tests.fakes import FakeEmbeddingFunction, FakeLLMClient, build_pdf


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    # _env_file=None : les tests ne lisent jamais le .env local ni la vraie clé
    return Settings(
        llm_provider="gemini",
        llm_model="test-model",
        llm_api_key="fake-key",
        # Base vectorielle propre à chaque test
        chroma_path=str(tmp_path / "chroma"),
        _env_file=None,
    )


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def policy_index(tmp_path: Path) -> PolicyIndex:
    """Index vide, isolé et sans modèle d'embedding à télécharger."""
    chroma = chromadb.PersistentClient(path=str(tmp_path / "index"), settings=ChromaSettings(anonymized_telemetry=False))
    return PolicyIndex(chroma, FakeEmbeddingFunction())


@pytest.fixture
def client(test_settings: Settings, fake_llm: FakeLLMClient) -> Iterator[TestClient]:
    app = create_app(test_settings, embedding_function=FakeEmbeddingFunction())
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
