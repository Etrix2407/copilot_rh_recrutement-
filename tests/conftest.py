import copy
import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path

import chromadb
import pytest
from chromadb.config import Settings as ChromaSettings
from fastapi.testclient import TestClient

from app.api.dependencies import get_llm_client
from app.config import Settings
from app.data.agenda import RECRUITER_AGENDA
from app.main import create_app
from app.services.candidate_store import CandidateStore
from app.services.policy_index import PolicyIndex
from tests.fakes import FakeEmbeddingFunction, FakeLLMClient, build_pdf


@pytest.fixture
def test_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    # Variables d'environnement du système ignorées (ex. DEMO_DATE définie dans la console de démo)
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    # _env_file=None : les tests ne lisent jamais le .env local ni la vraie clé
    return Settings(
        llm_provider="gemini",
        llm_model="test-model",
        llm_api_key="fake-key",
        # Base vectorielle propre à chaque test
        chroma_path=str(tmp_path / "chroma"),
        database_path=str(tmp_path / "candidates.db"),
        # Hôte utilisé par le TestClient
        allowed_hosts=["testserver"],
        _env_file=None,
    )


@pytest.fixture(autouse=True)
def restore_agenda() -> Iterator[None]:
    """Remet l'agenda du recruteur à son état initial après chaque test.

    Automatique : aucun test ne dépend de l'ordre d'exécution (tests/test_data.py compare l'agenda au cahier).
    """
    initial = copy.deepcopy(RECRUITER_AGENDA)
    yield
    # Modification en place : les outils gardent une référence vers ce même dictionnaire
    RECRUITER_AGENDA.clear()
    RECRUITER_AGENDA.update(initial)


SPEC_PATH = Path(__file__).parent.parent / "docs" / "cahier_des_charges.md"


@pytest.fixture(scope="session")
def spec_namespace() -> dict[str, object]:
    """Exécute les blocs Python du cahier des charges et renvoie les noms qu'ils définissent.

    Partagé par toute la session : un test qui appelle reserver_entretien doit remplacer
    AGENDA_RECRUTEUR par une copie (monkeypatch.setitem) pour ne pas modifier l'agenda du cahier.
    """
    spec = SPEC_PATH.read_text(encoding="utf-8")
    namespace: dict[str, object] = {}
    for block in re.findall(r"```python\n(.*?)```", spec, flags=re.DOTALL):
        exec(block, namespace)
    return namespace


@pytest.fixture
def store() -> Iterator[CandidateStore]:
    """Base de candidats en mémoire, fermée à la fin du test."""
    candidate_store = CandidateStore()
    yield candidate_store
    candidate_store.close()


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def policy_index(tmp_path: Path) -> PolicyIndex:
    """Index vide, isolé et sans modèle d'embedding à télécharger."""
    settings = ChromaSettings(anonymized_telemetry=False)
    chroma = chromadb.PersistentClient(path=str(tmp_path / "index"), settings=settings)
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
