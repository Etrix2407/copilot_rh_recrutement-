from collections.abc import Callable

from fastapi.testclient import TestClient

from app.data.candidates import SAMPLE_CANDIDATE_1, SAMPLE_CANDIDATE_2
from app.llm.base import LLMError
from tests.fakes import FakeLLMClient

PARSE_URL = "/api/candidates/parse"


def test_parse_text_returns_analyzed_candidate(
    client: TestClient, fake_llm: FakeLLMClient, valid_analysis_json: str
) -> None:
    fake_llm.json_answers = [valid_analysis_json]

    response = client.post(PARSE_URL, data={"text": "CV de Jean Dupont"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "analyzed"
    assert body["analysis"]["match_score"] == 90
    stored = client.app_state["candidate_store"].get(body["id"])
    assert stored.status == "analyzed"


def test_parse_pdf_file_sends_its_text_to_the_llm(
    client: TestClient,
    fake_llm: FakeLLMClient,
    valid_analysis_json: str,
    make_pdf: Callable[[str], bytes],
) -> None:
    fake_llm.json_answers = [valid_analysis_json]

    response = client.post(PARSE_URL, files={"file": ("cv.pdf", make_pdf("Jean Dupont FastAPI"), "application/pdf")})

    assert response.status_code == 200
    [message] = fake_llm.json_calls[0]["messages"]
    assert "Jean Dupont FastAPI" in message.content


def test_missing_input_is_rejected(client: TestClient) -> None:
    assert client.post(PARSE_URL).status_code == 422


def test_file_and_text_together_are_rejected(client: TestClient) -> None:
    response = client.post(PARSE_URL, data={"text": "CV"}, files={"file": ("cv.txt", b"CV", "text/plain")})

    assert response.status_code == 422


def test_scanned_pdf_returns_a_clear_error(client: TestClient, make_pdf: Callable[[str], bytes]) -> None:
    response = client.post(PARSE_URL, files={"file": ("scan.pdf", make_pdf(""), "application/pdf")})

    assert response.status_code == 422
    assert "aucun texte" in response.json()["detail"]


def test_invalid_llm_answers_return_502(client: TestClient, fake_llm: FakeLLMClient) -> None:
    fake_llm.json_answers = ["{}", "{}"]

    response = client.post(PARSE_URL, data={"text": "CV"})

    assert response.status_code == 502
    assert client.app_state["candidate_store"].list_all() == []


def test_llm_failure_returns_502(client: TestClient, fake_llm: FakeLLMClient) -> None:
    fake_llm.json_answers = [LLMError("quota dépassé")]

    response = client.post(PARSE_URL, data={"text": "CV"})

    assert response.status_code == 502
    assert "quota dépassé" in response.json()["detail"]


def test_list_returns_every_candidate(client: TestClient) -> None:
    store = client.app_state["candidate_store"]
    store.add(name="Jean Dupont", email="jean.dupont@email.com")
    store.add(name="Sophie Martin", email=None)

    response = client.get("/api/candidates")

    assert response.status_code == 200
    assert [candidate["name"] for candidate in response.json()] == ["Jean Dupont", "Sophie Martin"]


def test_list_is_empty_at_startup(client: TestClient) -> None:
    assert client.get("/api/candidates").json() == []


def test_samples_are_the_spec_cvs_unchanged(client: TestClient) -> None:
    response = client.get("/api/candidates/samples")

    assert response.status_code == 200
    assert response.json() == [
        {"label": "Jean Dupont", "text": SAMPLE_CANDIDATE_1},
        {"label": "Sophie Martin", "text": SAMPLE_CANDIDATE_2},
    ]
