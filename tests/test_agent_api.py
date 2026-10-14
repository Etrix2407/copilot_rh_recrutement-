import datetime
import json

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_llm_client
from app.config import Settings
from app.llm.base import LLMError, Message, Role, ToolCall
from app.main import create_app
from app.messages import LLM_UNAVAILABLE
from tests.fakes import FakeEmbeddingFunction, FakeLLMClient

CHAT_URL = "/api/agent/chat"


def parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    """Renvoie les événements (nom, données) d'un flux SSE, sans les commentaires de maintien."""
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        if fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def post_chat(client: TestClient, **payload: object) -> list[tuple[str, dict[str, object]]]:
    response = client.post(CHAT_URL, json=payload)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


def test_streams_tool_events_words_then_done(client: TestClient, fake_llm: FakeLLMClient) -> None:
    fake_llm.tool_answers = [
        Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(id="1", name="rechercher_creneaux_entretien", arguments={"date": "2026-10-15"})],
        ),
        Message(role=Role.ASSISTANT, content="4 créneaux libres."),
    ]

    events = post_chat(client, message="Créneaux du 2026-10-15 ?")

    assert [name for name, _ in events] == ["start", "tool_start", "tool_result", "token", "token", "token", "done"]
    assert events[2][1] == {
        "type": "tool_result",
        "name": "rechercher_creneaux_entretien",
        "success": True,
        "summary": "4 créneaux trouvés",
    }
    assert "".join(data["text"] for name, data in events if name == "token") == "4 créneaux libres."
    assert events[-1][1]["answer"] == "4 créneaux libres."
    # Même identifiant dès le début du flux et à la fin
    assert events[-1][1]["conversation_id"] == events[0][1]["conversation_id"]


def test_conversation_continues_with_its_history(client: TestClient, fake_llm: FakeLLMClient) -> None:
    fake_llm.tool_answers = [Message(role=Role.ASSISTANT, content="Bonjour !")]
    conversation_id = post_chat(client, message="Bonjour")[-1][1]["conversation_id"]
    fake_llm.tool_answers = [Message(role=Role.ASSISTANT, content="Toujours là.")]

    events = post_chat(client, message="Tu es là ?", conversation_id=conversation_id)

    assert events[-1][1]["conversation_id"] == conversation_id
    history = fake_llm.tool_calls[1]["messages"]
    assert [message.content for message in history] == ["Bonjour", "Bonjour !", "Tu es là ?"]


def test_llm_failure_ends_stream_with_error(client: TestClient, fake_llm: FakeLLMClient) -> None:
    fake_llm.tool_answers = [LLMError("quota dépassé")]

    events = post_chat(client, message="Bonjour")

    assert [name for name, _ in events] == ["start", "error"]
    assert events[-1][1]["message"] == LLM_UNAVAILABLE
    # L'id est connu du client même si la réponse échoue : la conversation peut être poursuivie
    assert events[0][1]["conversation_id"]


def test_unknown_conversation_returns_404(client: TestClient) -> None:
    response = client.post(CHAT_URL, json={"message": "Bonjour", "conversation_id": "inconnue"})

    assert response.status_code == 404


@pytest.mark.parametrize("message", ["", "   ", "x" * 2001])
def test_invalid_message_returns_422(client: TestClient, message: str) -> None:
    response = client.post(CHAT_URL, json={"message": message})

    assert response.status_code == 422


def test_demo_date_is_given_to_the_agent(test_settings: Settings, fake_llm: FakeLLMClient) -> None:
    settings = test_settings.model_copy(update={"demo_date": datetime.date(2026, 10, 14)})
    app = create_app(settings, embedding_function=FakeEmbeddingFunction())
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    fake_llm.tool_answers = [Message(role=Role.ASSISTANT, content="Bonjour")]

    with TestClient(app) as client:
        client.post(CHAT_URL, json={"message": "Bonjour"})

    assert "Date du jour : 2026-10-14." in fake_llm.tool_calls[0]["system"]
