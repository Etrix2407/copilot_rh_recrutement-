import asyncio

import pytest

from app.llm.base import LLMError, Message, Role, ToolCall
from app.models.agent import AgentEvent, DoneEvent, ErrorEvent, StartEvent
from app.services.agent_chat import (
    CONVERSATION_TOO_LONG,
    INTERRUPTED,
    MAX_HISTORY_MESSAGES,
    UNEXPECTED_ERROR,
    ConversationNotFoundError,
    ConversationStore,
    chat,
)
from app.services.candidate_store import CandidateStore
from tests.fakes import FakeLLMClient


def run_chat(fake_llm: FakeLLMClient, conversations: ConversationStore, conversation_id: str) -> list[AgentEvent]:
    async def collect() -> list[AgentEvent]:
        stream = chat(
            "Bonjour",
            conversation_id=conversation_id,
            history=[],
            llm=fake_llm,
            store=CandidateStore(),
            conversations=conversations,
        )
        return [event async for event in stream]

    return asyncio.run(collect())


def test_open_without_id_starts_new_conversation() -> None:
    conversation_id, history = ConversationStore().open(None)

    assert conversation_id
    assert history == []


def test_open_unknown_id_fails() -> None:
    with pytest.raises(ConversationNotFoundError):
        ConversationStore().open("inconnue")


def test_finished_answer_is_saved(fake_llm: FakeLLMClient) -> None:
    conversations = ConversationStore()
    fake_llm.tool_answers = [Message(role=Role.ASSISTANT, content="Salut")]

    events = run_chat(fake_llm, conversations, "conv-1")

    assert events[-1] == DoneEvent(conversation_id="conv-1", answer="Salut")
    _, history = conversations.open("conv-1")
    assert [message.content for message in history] == ["Bonjour", "Salut"]


def test_interrupted_answer_is_not_saved(fake_llm: FakeLLMClient) -> None:
    conversations = ConversationStore()
    fake_llm.tool_answers = [LLMError("quota")]

    events = run_chat(fake_llm, conversations, "conv-1")

    assert isinstance(events[-1], ErrorEvent)
    with pytest.raises(ConversationNotFoundError):
        conversations.open("conv-1")


def test_unexpected_error_becomes_error_event(fake_llm: FakeLLMClient) -> None:
    # Aucune réponse prévue : le faux LLM lève IndexError, comme le ferait un bug
    events = run_chat(fake_llm, ConversationStore(), "conv-1")

    assert events == [StartEvent(conversation_id="conv-1"), ErrorEvent(message=UNEXPECTED_ERROR)]


def test_oldest_conversations_are_forgotten() -> None:
    conversations = ConversationStore(max_conversations=2)
    for conversation_id in ("a", "b", "c"):
        conversations.save(conversation_id, [])

    with pytest.raises(ConversationNotFoundError):
        conversations.open("a")
    assert conversations.open("c") == ("c", [])


def test_too_long_conversation_is_refused(fake_llm: FakeLLMClient) -> None:
    history = [Message(role=Role.USER, content="…")] * MAX_HISTORY_MESSAGES

    async def collect() -> list[AgentEvent]:
        stream = chat(
            "Encore ?",
            conversation_id="long",
            history=history,
            llm=fake_llm,
            store=CandidateStore(),
            conversations=ConversationStore(),
        )
        return [event async for event in stream]

    assert asyncio.run(collect()) == [StartEvent(conversation_id="long"), ErrorEvent(message=CONVERSATION_TOO_LONG)]
    assert fake_llm.tool_calls == []


def test_interrupted_answer_keeps_the_tools_already_run(fake_llm: FakeLLMClient) -> None:
    conversations = ConversationStore()
    search = ToolCall(id="1", name="rechercher_creneaux_entretien", arguments={"date": "2026-10-16"})
    fake_llm.tool_answers = [Message(role=Role.ASSISTANT, tool_calls=[search]), LLMError("quota")]

    events = run_chat(fake_llm, conversations, "conv-1")

    assert isinstance(events[-1], ErrorEvent)
    _, history = conversations.open("conv-1")
    assert [message.role for message in history] == [Role.USER, Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]
    assert history[-1].content == INTERRUPTED


def test_forget_mentions_erases_conversations_about_a_candidate() -> None:
    conversations = ConversationStore()
    conversations.save("a", [Message(role=Role.USER, content="Réserve Jean Dupont (JEAN.dupont@email.com)")])
    conversations.save("b", [Message(role=Role.USER, content="Bonjour")])

    forgotten = conversations.forget_mentions(["jean.dupont@email.com", "Jean Dupont"])

    assert forgotten == 1
    with pytest.raises(ConversationNotFoundError):
        conversations.open("a")
    assert conversations.open("b")[1]


def test_forget_mentions_ignores_empty_terms() -> None:
    conversations = ConversationStore()
    conversations.save("a", [Message(role=Role.USER, content="Bonjour")])

    assert conversations.forget_mentions(["", "   "]) == 0
