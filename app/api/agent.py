from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.api.dependencies import CandidateStoreDep, ConversationStoreDep, LLMClientDep, SettingsDep
from app.api.rate_limit import enforce_llm_rate_limit
from app.llm.base import Message
from app.models.agent import ChatRequest
from app.services.agent_chat import (
    CONVERSATION_BUSY,
    ConversationNotFoundError,
    ConversationTooLongError,
    chat,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])


@dataclass(frozen=True)
class ChatTurn:
    """Demande validée et conversation retrouvée, prêtes pour le flux."""

    message: str
    conversation_id: str
    history: list[Message]
    # Effacements RGPD connus à l'ouverture : un effacement ultérieur empêche d'enregistrer le tour
    erasures_seen: int
    # Jeton du tour : seul ce tour peut libérer la conversation (voir ConversationStore.end_turn)
    turn_token: str


async def open_chat_turn(body: ChatRequest, request: Request, conversations: ConversationStoreDep) -> ChatTurn:
    """Exécutée avant l'ouverture du flux : une erreur donne encore un vrai code HTTP (404, 409, 429).

    FastAPI ne l'appelle que si le corps est valide : une demande invalide ne consomme pas le quota.
    Une conversation inconnue donne 404 ; trop longue ou déjà occupée par un tour, 409. La
    conversation, nouvelle ou existante, est ensuite marquée occupée (un seul tour à la fois) ;
    chat() la libère à la fin du tour. Le quota n'est consommé qu'après tous ces contrôles.
    Asynchrone : elle tourne sur la boucle d'événements, comme les autres utilisateurs du limiteur.
    """
    erasures_seen = conversations.erasure_count
    try:
        conversation_id, history = conversations.open(body.conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ConversationTooLongError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    turn_token = conversations.start_turn(conversation_id)
    if turn_token is None:
        raise HTTPException(status.HTTP_409_CONFLICT, CONVERSATION_BUSY)
    try:
        enforce_llm_rate_limit(request)
    except HTTPException:
        # Aucun tour ne commence : la conversation ne doit pas rester occupée
        conversations.end_turn(conversation_id, turn_token)
        raise
    return ChatTurn(
        message=body.message,
        conversation_id=conversation_id,
        history=history,
        erasures_seen=erasures_seen,
        turn_token=turn_token,
    )


@router.post("/chat", response_class=EventSourceResponse)
async def chat_with_agent(
    turn: Annotated[ChatTurn, Depends(open_chat_turn)],
    llm: LLMClientDep,
    store: CandidateStoreDep,
    conversations: ConversationStoreDep,
    settings: SettingsDep,
) -> AsyncIterator[ServerSentEvent]:
    """Chat avec l'agent en SSE : événements start, token, tool_start, tool_result, puis done ou error."""
    async for event in chat(
        turn.message,
        conversation_id=turn.conversation_id,
        history=turn.history,
        llm=llm,
        store=store,
        conversations=conversations,
        today=settings.demo_date,
        erasures_seen=turn.erasures_seen,
        turn_token=turn.turn_token,
    ):
        yield ServerSentEvent(event=event.type, data=event)
