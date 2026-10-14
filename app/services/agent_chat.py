"""Conversations avec l'agent : historique en mémoire et flux d'événements pour le chat."""

import logging
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator, Sequence

from app.llm.base import LLMClient, LLMError, Message
from app.models.agent import AgentEvent, DoneEvent, ErrorEvent
from app.services.agent import AgentReply, stream_agent
from app.services.candidate_store import CandidateStore

logger = logging.getLogger(__name__)

LLM_UNAVAILABLE = "L'assistant est momentanément indisponible. Réessayez dans quelques instants."
UNEXPECTED_ERROR = "Une erreur inattendue est survenue. Réessayez ou reformulez votre demande."
CONVERSATION_TOO_LONG = "Cette conversation est trop longue. Commencez une nouvelle conversation."

# Plafonds mémoire : au-delà, les plus anciennes conversations sont oubliées
MAX_CONVERSATIONS = 100
# Messages d'un historique (appels et résultats d'outils compris) : tout est renvoyé au LLM à chaque tour
MAX_HISTORY_MESSAGES = 60


class ConversationNotFoundError(Exception):
    def __init__(self, conversation_id: str) -> None:
        super().__init__(f"Aucune conversation avec l'identifiant {conversation_id!r}.")


class ConversationStore:
    """Historiques des conversations en mémoire : ils sont vidés à chaque redémarrage de l'API."""

    def __init__(self, max_conversations: int = MAX_CONVERSATIONS) -> None:
        self._conversations: OrderedDict[str, list[Message]] = OrderedDict()
        self._max_conversations = max_conversations

    def open(self, conversation_id: str | None) -> tuple[str, list[Message]]:
        """Renvoie l'id et l'historique de la conversation ; sans id, en démarre une nouvelle.

        Lève ConversationNotFoundError si l'id est inconnu.
        """
        if conversation_id is None:
            return uuid.uuid4().hex, []
        try:
            return conversation_id, list(self._conversations[conversation_id])
        except KeyError:
            raise ConversationNotFoundError(conversation_id) from None

    def save(self, conversation_id: str, messages: Sequence[Message]) -> None:
        self._conversations[conversation_id] = list(messages)
        self._conversations.move_to_end(conversation_id)
        while len(self._conversations) > self._max_conversations:
            self._conversations.popitem(last=False)


async def chat(
    message: str,
    *,
    conversation_id: str,
    history: Sequence[Message],
    llm: LLMClient,
    store: CandidateStore,
    conversations: ConversationStore,
) -> AsyncIterator[AgentEvent]:
    """Produit les événements de la réponse de l'agent, puis done ou error.

    L'historique n'est enregistré qu'une fois la réponse terminée : une réponse
    interrompue (erreur, déconnexion du client) ne laisse pas d'historique incohérent.
    """
    if len(history) >= MAX_HISTORY_MESSAGES:
        yield ErrorEvent(message=CONVERSATION_TOO_LONG)
        return
    try:
        async for item in stream_agent(message, history=history, llm=llm, store=store):
            if isinstance(item, AgentReply):
                conversations.save(conversation_id, item.messages)
                yield DoneEvent(conversation_id=conversation_id, answer=item.answer)
            else:
                yield item
    except LLMError as exc:
        logger.warning("Réponse de l'agent interrompue : %s", exc)
        yield ErrorEvent(message=LLM_UNAVAILABLE)
    # Dernier rempart du flux : le client reçoit un message propre au lieu d'une connexion coupée
    except Exception:
        logger.exception("Erreur inattendue dans le chat de l'agent")
        yield ErrorEvent(message=UNEXPECTED_ERROR)
