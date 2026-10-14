import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_candidate_store
from app.api.errors import INTERNAL_ERROR
from app.config import Settings
from app.main import create_app
from tests.fakes import FakeEmbeddingFunction


@pytest.mark.parametrize(
    ("request_kwargs", "detail"),
    [
        ({"json": {}}, "Champ « question » : champ obligatoire."),
        ({"json": {"question": "x" * 1001}}, "Champ « question » : 1000 caractères maximum."),
        (
            {"content": "{", "headers": {"Content-Type": "application/json"}},
            "Le corps de la requête n'est pas un JSON valide.",
        ),
    ],
    ids=["manquant", "trop_long", "json_invalide"],
)
def test_validation_errors_have_a_readable_detail(
    client: TestClient, request_kwargs: dict[str, object], detail: str
) -> None:
    response = client.post("/api/rag/ask", **request_kwargs)

    assert response.status_code == 422
    assert response.json()["detail"] == detail
    assert response.json()["errors"]


def test_malformed_date_has_a_readable_detail(client: TestClient) -> None:
    response = client.get("/api/interviews/slots", params={"candidate_id": "x", "date": "demain"})

    assert response.status_code == 422
    assert response.json()["detail"] == "Champ « date » : date invalide, format attendu AAAA-MM-JJ."


def test_unexpected_error_hides_internal_details(test_settings: Settings) -> None:
    app = create_app(test_settings, embedding_function=FakeEmbeddingFunction())

    def broken_store() -> None:
        raise RuntimeError("secret interne")

    app.dependency_overrides[get_candidate_store] = broken_store
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/candidates")

    assert response.status_code == 500
    assert response.json() == {"detail": INTERNAL_ERROR}


@pytest.mark.parametrize(
    ("method", "path", "status", "detail"),
    [
        ("GET", "/api/inconnu", 404, "Adresse introuvable."),
        ("PUT", "/api/rag/ask", 405, "Méthode non autorisée pour cette adresse."),
    ],
)
def test_framework_errors_are_in_french(client: TestClient, method: str, path: str, status: int, detail: str) -> None:
    response = client.request(method, path)

    assert response.status_code == status
    assert response.json() == {"detail": detail}


def test_validation_errors_do_not_echo_the_input(client: TestClient) -> None:
    response = client.post("/api/rag/ask", json={"question": "secret " * 200})

    assert "secret" not in response.text
