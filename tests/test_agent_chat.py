import asyncio

import pytest

from app.llm.base import LLMError, Message, Role
from app.models.agent import AgentEvent, DoneEvent, ErrorEvent
from app.services.agent_chat import UNEXPECTED_ERROR, ConversationNotFoundError, ConversationStore, chat
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

    assert events == [ErrorEvent(message=UNEXPECTED_ERROR)]
