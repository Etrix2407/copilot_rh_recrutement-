from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.docs import REDOC_VERSION, SWAGGER_UI_VERSION
from app.config import Settings
from app.data.hr_policies import HR_POLICIES
from app.llm.gemini import GeminiClient
from app.main import create_app
from app.services.candidate_store import CandidateStore
from app.services.policy_index import PolicyIndex
from tests.fakes import FakeEmbeddingFunction


def test_startup_creates_shared_objects(client: TestClient) -> None:
    state = client.app_state

    assert isinstance(state["llm_client"], GeminiClient)
    assert isinstance(state["candidate_store"], CandidateStore)
    assert isinstance(state["policy_index"], PolicyIndex)


def test_startup_indexes_every_hr_policy(client: TestClient) -> None:
    assert client.app_state["policy_index"].count() == len(HR_POLICIES)


def test_cors_allows_configured_origin(test_settings: Settings) -> None:
    settings = test_settings.model_copy(update={"cors_origins": ["http://localhost:5173"]})
    app = create_app(settings, embedding_function=FakeEmbeddingFunction())

    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_ignores_unknown_origin(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://evil.example"})

    assert "access-control-allow-origin" not in response.headers


def test_frontend_is_served_at_root(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Copilot RH" in response.text


def test_frontend_assets_are_served(client: TestClient) -> None:
    response = client.get("/js/main.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_api_docs_stay_reachable_despite_frontend(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/health").status_code == 200


def test_security_headers_are_set_on_the_interface(client: TestClient) -> None:
    response = client.get("/")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_docs_keep_working_without_csp(client: TestClient) -> None:
    response = client.get("/docs")

    assert response.status_code == 200
    assert "content-security-policy" not in response.headers


def test_post_from_another_site_is_refused(client: TestClient) -> None:
    response = client.post("/api/rag/ask", json={"question": "RTT ?"}, headers={"Origin": "http://evil.example"})

    assert response.status_code == 403


def test_post_from_the_interface_itself_is_allowed(client: TestClient) -> None:
    # Même origine que le serveur : la requête atteint la route (ici refusée pour un corps invalide)
    response = client.post("/api/rag/ask", json={}, headers={"Origin": "http://testserver"})

    assert response.status_code == 422


def test_unknown_host_is_refused(client: TestClient) -> None:
    # « DNS rebinding » : un site piégé qui pointe vers 127.0.0.1 envoie son propre nom d'hôte
    response = client.get("/api/candidates", headers={"Host": "evil.example"})

    assert response.status_code == 400


def test_cross_site_request_without_origin_is_refused(client: TestClient) -> None:
    response = client.post("/api/rag/ask", json={"question": "RTT ?"}, headers={"Sec-Fetch-Site": "cross-site"})

    assert response.status_code == 403


def test_too_large_json_body_is_refused(client: TestClient) -> None:
    response = client.post("/api/rag/ask", json={"question": "x" * 100_000})

    assert response.status_code == 413


def test_too_large_body_without_content_length_is_refused(client: TestClient) -> None:
    # Envoi « chunked » : la taille n'est pas annoncée, les octets sont comptés à la réception
    def chunks() -> Iterator[bytes]:
        yield b'{"question": "'
        for _ in range(100):
            yield b"x" * 1000
        yield b'"}'

    response = client.post("/api/rag/ask", content=chunks(), headers={"Content-Type": "application/json"})

    assert response.status_code == 413


def test_json_limit_does_not_depend_on_the_declared_content_type(client: TestClient) -> None:
    body = '{"question": "' + "x" * 100_000 + '"}'

    response = client.post("/api/rag/ask", content=body, headers={"Content-Type": "text/plain"})

    assert response.status_code == 413


def test_refusals_also_carry_security_headers(client: TestClient) -> None:
    response = client.get("/api/candidates", headers={"Host": "evil.example"})

    assert response.status_code == 400
    assert response.headers["x-content-type-options"] == "nosniff"


def test_docs_use_pinned_swagger_and_redoc_versions(client: TestClient) -> None:
    docs = client.get("/docs")
    redoc = client.get("/redoc")

    assert docs.status_code == 200 and redoc.status_code == 200
    assert f"swagger-ui-dist@{SWAGGER_UI_VERSION}/swagger-ui-bundle.js" in docs.text
    assert f"redoc@{REDOC_VERSION}/" in redoc.text
    # La spécification OpenAPI reste servie, et les pages de doc n'y figurent pas
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/agent/chat" in paths and "/docs" not in paths


@pytest.mark.parametrize("path", ["/docs%2f..%2findex.html", "/docs/..%2f", "/redoc%2f..%2findex.html", "/docsx"])
def test_csp_cannot_be_dropped_by_a_path_starting_with_docs(client: TestClient, path: str) -> None:
    response = client.get(path)

    # Quelle que soit la page obtenue, elle garde la CSP (seuls /docs et /redoc exacts en sont privés)
    assert "content-security-policy" in response.headers


def test_no_page_can_be_framed_not_even_the_docs(client: TestClient) -> None:
    for path in ("/", "/docs", "/redoc", "/api/candidates"):
        assert client.get(path).headers["x-frame-options"] == "DENY"


def test_api_responses_are_never_cached(client: TestClient) -> None:
    assert client.get("/api/candidates").headers["cache-control"] == "no-store"
    # L'interface elle-même peut être mise en cache : elle ne contient aucune donnée personnelle
    assert client.get("/").headers.get("cache-control") != "no-store"
