import datetime
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.agent import open_chat_turn
from app.api.dependencies import get_conversation_store, get_llm_client
from app.config import Settings
from app.llm.base import LLMError, Message, Role, ToolCall
from app.main import create_app
from app.messages import LLM_UNAVAILABLE
from app.models.agent import ChatRequest
from app.services.agent_chat import CONVERSATION_TOO_LONG, MAX_HISTORY_MESSAGES, TURN_TIMEOUT_SECONDS, ConversationStore
from tests.fakes import FakeEmbeddingFunction, FakeLLMClient, parse_sse

CHAT_URL = "/api/agent/chat"


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


# --- Un seul tour à la fois par conversation (deux onglets) ---


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def conversations(clock: FakeClock) -> ConversationStore:
    store = ConversationStore(clock=clock)
    store.save("conv-1", [Message(role=Role.USER, content="Bonjour"), Message(role=Role.ASSISTANT, content="Salut")])
    return store


@pytest.fixture
def limited_client(
    test_settings: Settings, fake_llm: FakeLLMClient, conversations: ConversationStore
) -> Iterator[TestClient]:
    """Application limitée à 1 demande au LLM par minute, avec un magasin de conversations contrôlé."""
    settings = test_settings.model_copy(update={"llm_requests_per_minute": 1})
    app = create_app(settings, embedding_function=FakeEmbeddingFunction())
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    app.dependency_overrides[get_conversation_store] = lambda: conversations
    fake_llm.tool_answers = [Message(role=Role.ASSISTANT, content="Bonjour")]
    with TestClient(app) as client:
        yield client


def test_second_turn_on_busy_conversation_returns_409_without_llm_nor_quota(
    limited_client: TestClient, fake_llm: FakeLLMClient, conversations: ConversationStore
) -> None:
    conversations.start_turn("conv-1")  # tour en cours dans un autre onglet

    response = limited_client.post(CHAT_URL, json={"message": "Encore ?", "conversation_id": "conv-1"})

    assert response.status_code == 409
    assert response.json()["detail"] == "Une réponse est déjà en cours pour cette conversation."
    assert fake_llm.tool_calls == []
    # Le quota (1 par minute) n'a pas été consommé
    assert limited_client.post(CHAT_URL, json={"message": "Bonjour"}).status_code == 200


def test_conversation_is_released_after_the_turn(client: TestClient, fake_llm: FakeLLMClient) -> None:
    fake_llm.tool_answers = [Message(role=Role.ASSISTANT, content="Bonjour")] * 3
    conversation_id = post_chat(client, message="Bonjour")[-1][1]["conversation_id"]

    post_chat(client, message="Encore ?", conversation_id=conversation_id)
    events = post_chat(client, message="Et encore ?", conversation_id=conversation_id)

    assert events[-1][0] == "done"


def test_busy_conversation_expires(
    limited_client: TestClient, conversations: ConversationStore, clock: FakeClock
) -> None:
    # Flux jamais lu (client parti avant le premier événement) : la conversation n'est pas bloquée à vie
    conversations.start_turn("conv-1")
    clock.now = TURN_TIMEOUT_SECONDS

    response = limited_client.post(CHAT_URL, json={"message": "Encore ?", "conversation_id": "conv-1"})

    assert response.status_code == 200


def test_rate_limited_turn_does_not_keep_the_conversation_busy(
    limited_client: TestClient, conversations: ConversationStore
) -> None:
    assert limited_client.post(CHAT_URL, json={"message": "Bonjour"}).status_code == 200

    response = limited_client.post(CHAT_URL, json={"message": "Encore ?", "conversation_id": "conv-1"})

    assert response.status_code == 429
    assert conversations.start_turn("conv-1") is not None


def test_erasure_during_turn_is_not_undone(
    limited_client: TestClient, conversations: ConversationStore, fake_llm: FakeLLMClient
) -> None:
    # Effacement RGPD pendant que l'agent répond (simulé au moment de l'appel au LLM)
    original = fake_llm.stream_with_tools

    def erase_then_answer(*args: object, **kwargs: object) -> AsyncIterator[str | Message]:
        conversations.forget_all()
        return original(*args, **kwargs)

    fake_llm.stream_with_tools = erase_then_answer  # type: ignore[method-assign]

    events = post_chat(limited_client, message="Réserve Jean Dupont", conversation_id="conv-1")

    assert events[-1][0] == "done"
    response = limited_client.post(CHAT_URL, json={"message": "Encore ?", "conversation_id": "conv-1"})
    assert response.status_code == 404


def test_new_conversation_is_busy_not_unknown_during_its_first_turn(
    limited_client: TestClient,
    conversations: ConversationStore,
    fake_llm: FakeLLMClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Un second message envoyé avec l'id reçu dans start, pendant le premier tour, reçoit 409
    started: list[str] = []
    original_start = conversations.start_turn

    def recording_start(conversation_id: str) -> str | None:
        started.append(conversation_id)
        return original_start(conversation_id)

    monkeypatch.setattr(conversations, "start_turn", recording_start)
    original_stream = fake_llm.stream_with_tools
    refusals: list[HTTPException] = []

    async def second_message_meanwhile(*args: Any, **kwargs: Any) -> AsyncIterator[str | Message]:
        body = ChatRequest(message="Encore ?", conversation_id=started[0])
        with pytest.raises(HTTPException) as refused:
            # Refusé avant le limiteur : la requête n'est pas nécessaire
            await open_chat_turn(body, None, conversations)  # type: ignore[arg-type]
        refusals.append(refused.value)
        async for item in original_stream(*args, **kwargs):
            yield item

    fake_llm.stream_with_tools = second_message_meanwhile  # type: ignore[method-assign]

    events = post_chat(limited_client, message="Bonjour")

    assert events[-1][0] == "done"
    assert [refusal.status_code for refusal in refusals] == [409]
    # Le premier tour terminé, la conversation est enregistrée et libre
    assert conversations.open(events[0][1]["conversation_id"])[1]
    assert conversations.start_turn(events[0][1]["conversation_id"]) is not None


def test_too_long_conversation_returns_409_without_llm_nor_quota(
    limited_client: TestClient, fake_llm: FakeLLMClient, conversations: ConversationStore
) -> None:
    conversations.save("long", [Message(role=Role.USER, content="…")] * MAX_HISTORY_MESSAGES)

    response = limited_client.post(CHAT_URL, json={"message": "Encore ?", "conversation_id": "long"})

    assert response.status_code == 409
    assert response.json()["detail"] == CONVERSATION_TOO_LONG
    assert fake_llm.tool_calls == []
    # Le quota (1 par minute) n'a pas été consommé, et la conversation n'est pas restée occupée
    assert limited_client.post(CHAT_URL, json={"message": "Bonjour"}).status_code == 200
    assert conversations.start_turn("long") is not None
