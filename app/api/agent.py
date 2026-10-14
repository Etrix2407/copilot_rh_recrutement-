from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.api.dependencies import CandidateStoreDep, ConversationStoreDep, LLMClientDep
from app.llm.base import Message
from app.models.agent import ChatRequest
from app.services.agent_chat import ConversationNotFoundError, chat

router = APIRouter(prefix="/api/agent", tags=["agent"])


def open_conversation(request: ChatRequest, conversations: ConversationStoreDep) -> tuple[str, list[Message]]:
    """Exécutée avant l'ouverture du flux : une conversation inconnue donne un vrai 404."""
    try:
        return conversations.open(request.conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/chat", response_class=EventSourceResponse)
async def chat_with_agent(
    request: ChatRequest,
    conversation: Annotated[tuple[str, list[Message]], Depends(open_conversation)],
    llm: LLMClientDep,
    store: CandidateStoreDep,
    conversations: ConversationStoreDep,
) -> AsyncIterator[ServerSentEvent]:
    """Chat avec l'agent en SSE : événements token, tool_start, tool_result, puis done ou error."""
    conversation_id, history = conversation
    async for event in chat(
        request.message,
        conversation_id=conversation_id,
        history=history,
        llm=llm,
        store=store,
        conversations=conversations,
    ):
        yield ServerSentEvent(event=event.type, data=event)
