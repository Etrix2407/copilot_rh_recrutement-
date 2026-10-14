from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_llm_client
from app.api.errors import LLM_UNAVAILABLE
from app.config import Settings
from app.data.candidates import SAMPLE_CANDIDATE_1, SAMPLE_CANDIDATE_2
from app.llm.base import LLMError, Message, Role, ToolCall
from app.main import create_app
from app.services.agent_chat import ConversationNotFoundError
from app.services.cv_reader import MAX_CV_BYTES, MAX_CV_CHARS
from tests.fakes import FakeEmbeddingFunction, FakeLLMClient

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
    # Le détail interne de l'erreur reste dans les logs
    assert response.json()["detail"] == LLM_UNAVAILABLE


@pytest.mark.parametrize(
    ("answers", "expected_status"),
    [("valid", 200), (["{}", "{}"], 502), ([LLMError("quota")], 502)],
)
def test_cv_content_is_never_logged(
    client: TestClient,
    fake_llm: FakeLLMClient,
    valid_analysis_json: str,
    caplog: pytest.LogCaptureFixture,
    answers: str | list,
    expected_status: int,
) -> None:
    fake_llm.json_answers = [valid_analysis_json] if answers == "valid" else answers
    secret = "Rue-des-Tilleuls-42-Tel-0470123456"

    with caplog.at_level("DEBUG"):
        response = client.post(PARSE_URL, data={"text": f"CV de Jean Dupont, {secret}"})

    assert response.status_code == expected_status
    assert secret not in caplog.text


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


def test_too_long_text_is_rejected(client: TestClient) -> None:
    response = client.post(PARSE_URL, data={"text": "x" * (MAX_CV_CHARS + 1)})

    assert response.status_code == 422
    assert "trop long" in response.json()["detail"]


def test_too_large_file_is_rejected_without_calling_the_llm(client: TestClient, fake_llm: FakeLLMClient) -> None:
    files = {"file": ("cv.txt", b"x" * (MAX_CV_BYTES + 1), "text/plain")}

    response = client.post(PARSE_URL, files=files)

    assert response.status_code == 413
    assert "trop volumineux" in response.json()["detail"]
    assert fake_llm.json_calls == []
    assert client.app_state["candidate_store"].list_all() == []


def test_delete_removes_candidate(client: TestClient) -> None:
    candidate = client.app_state["candidate_store"].add(name="Jean Dupont", email=None)

    response = client.delete(f"/api/candidates/{candidate.id}")

    assert response.status_code == 204
    assert client.get("/api/candidates").json() == []


def test_delete_unknown_candidate_returns_404(client: TestClient) -> None:
    assert client.delete("/api/candidates/inconnu").status_code == 404


def test_delete_also_forgets_conversations_about_the_candidate(client: TestClient) -> None:
    candidate = client.app_state["candidate_store"].add(name="Jean Dupont", email="jean.dupont@email.com")
    conversations = client.app_state["conversation_store"]
    conversations.save("conv", [Message(role=Role.USER, content="Planifie jean.dupont@email.com")])

    client.delete(f"/api/candidates/{candidate.id}")

    with pytest.raises(ConversationNotFoundError):
        conversations.open("conv")


def test_rejected_upload_does_not_consume_the_quota(test_settings: Settings, fake_llm: FakeLLMClient) -> None:
    settings = test_settings.model_copy(update={"llm_requests_per_minute": 1})
    app = create_app(settings, embedding_function=FakeEmbeddingFunction())
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    fake_llm.json_answers = [LLMError("quota")]

    with TestClient(app) as limited:
        for _ in range(3):
            response = limited.post(PARSE_URL, files={"file": ("cv.docx", b"Jean", "application/octet-stream")})
            assert response.status_code == 422
        both = limited.post(PARSE_URL, files={"file": ("cv.txt", b"Jean", "text/plain")}, data={"text": "Jean"})
        assert both.status_code == 422
        # Le quota d'une requête est intact : la demande valide atteint le LLM (ici en échec simulé, 502)
        assert limited.post(PARSE_URL, data={"text": "CV de Jean"}).status_code == 502


def test_delete_works_after_a_real_agent_conversation(client: TestClient) -> None:
    # Gemini joint aux appels d'outils une « thought signature » binaire, absente du faux LLM
    candidate = client.app_state["candidate_store"].add(name="Jean Dupont", email="jean.dupont@email.com")
    call = ToolCall(
        id="1",
        name="reserver_entretien",
        arguments={"candidat_nom": "Jean Dupont", "email": "jean.dupont@email.com"},
        signature=b"\xff\xfe\x00binaire",
    )
    client.app_state["conversation_store"].save("conv", [Message(role=Role.ASSISTANT, tool_calls=[call])])

    response = client.delete(f"/api/candidates/{candidate.id}")

    assert response.status_code == 204
    with pytest.raises(ConversationNotFoundError):
        client.app_state["conversation_store"].open("conv")


def test_unknown_candidate_message_does_not_echo_the_identifier(client: TestClient) -> None:
    sent = "<img src=x>" + "x" * 5000

    deleted = client.delete(f"/api/candidates/{sent}")
    slots = client.get("/api/interviews/slots", params={"candidate_id": sent, "date": "2026-10-15"})

    for response in (deleted, slots):
        assert response.status_code == 404
        assert response.json() == {"detail": "Candidat introuvable."}
