from fastapi.testclient import TestClient

from app.llm.gemini import GeminiClient
from app.data.hr_policies import HR_POLICIES
from app.services.candidate_store import CandidateStore
from app.services.policy_index import PolicyIndex


def test_startup_creates_shared_objects(client: TestClient) -> None:
    state = client.app.state

    assert isinstance(state.llm_client, GeminiClient)
    assert isinstance(state.candidate_store, CandidateStore)
    assert isinstance(state.policy_index, PolicyIndex)


def test_startup_indexes_every_hr_policy(client: TestClient) -> None:
    assert client.app.state.policy_index.count() == len(HR_POLICIES)


def test_cors_allows_configured_origin(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_ignores_unknown_origin(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://evil.example"})

    assert "access-control-allow-origin" not in response.headers
