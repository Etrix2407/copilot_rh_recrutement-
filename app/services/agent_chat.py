"""Conversations avec l'agent : historique en mémoire et flux d'événements pour le chat."""

import datetime
import logging
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator, Iterable, Sequence

from app.llm.base import LLMClient, LLMError, Message, Role
from app.messages import LLM_UNAVAILABLE
from app.models.agent import AgentEvent, DoneEvent, ErrorEvent, StartEvent
from app.services.agent import AgentCheckpoint, AgentReply, stream_agent
from app.services.candidate_store import CandidateStore

logger = logging.getLogger(__name__)

UNEXPECTED_ERROR = "Une erreur inattendue est survenue. Réessayez ou reformulez votre demande."
# Clôt l'historique d'une réponse interrompue après des outils (réservation, statut…)
INTERRUPTED = "(Réponse interrompue après l'exécution des outils ci-dessus.)"
CONVERSATION_TOO_LONG = "Cette conversation est trop longue. Commencez une nouvelle conversation."

# Plafonds mémoire : au-delà, les plus anciennes conversations sont oubliées
MAX_CONVERSATIONS = 100
# Taille d'historique (appels et résultats d'outils compris) au-delà de laquelle une conversation
# n'accepte plus de nouvelle demande : tout l'historique est renvoyé au LLM à chaque tour
MAX_HISTORY_MESSAGES = 60


class ConversationNotFoundError(Exception):
    def __init__(self, conversation_id: str) -> None:
        super().__init__("Cette conversation n'existe pas ou a expiré.")
        self.conversation_id = conversation_id


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

    def forget_mentions(self, terms: Iterable[str]) -> int:
        """Oublie les conversations qui mentionnent l'un des termes (nom, email), sans tenir compte de la casse.

        Utilisé pour l'effacement d'un candidat (RGPD). Renvoie le nombre de conversations oubliées.
        """
        wanted = [term.casefold() for term in terms if term and term.strip()]
        forgotten = [
            conversation_id
            for conversation_id, messages in self._conversations.items()
            if any(term in _searchable_text(messages) for term in wanted)
        ]
        for conversation_id in forgotten:
            del self._conversations[conversation_id]
        return len(forgotten)


def _searchable_text(messages: Sequence[Message]) -> str:
    # Le JSON couvre le texte, les arguments des outils et leurs résultats
    return "\n".join(message.model_dump_json() for message in messages).casefold()


async def chat(
    message: str,
    *,
    conversation_id: str,
    history: Sequence[Message],
    llm: LLMClient,
    store: CandidateStore,
    conversations: ConversationStore,
    today: datetime.date | None = None,
) -> AsyncIterator[AgentEvent]:
    """Produit start, les événements de la réponse de l'agent, puis done ou error.

    L'événement start transmet l'id de la conversation dès le début : le client peut la
    poursuivre même si la réponse est interrompue (erreur, bouton « Arrêter », coupure).
    L'historique complet est enregistré à la fin de la réponse. Si elle est interrompue
    après l'exécution d'outils, l'historique est enregistré jusqu'au dernier outil : une
    réservation déjà faite reste connue au tour suivant.
    """
    yield StartEvent(conversation_id=conversation_id)
    if len(history) >= MAX_HISTORY_MESSAGES:
        yield ErrorEvent(message=CONVERSATION_TOO_LONG)
        return
    checkpoint: list[Message] | None = None
    finished = False
    try:
        async for item in stream_agent(message, history=history, llm=llm, store=store, today=today):
            if isinstance(item, AgentCheckpoint):
                checkpoint = item.messages
            elif isinstance(item, AgentReply):
                conversations.save(conversation_id, item.messages)
                finished = True
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
    finally:
        # Exécuté aussi quand le client se déconnecte (le générateur est alors fermé)
        if not finished and checkpoint is not None:
            conversations.save(conversation_id, [*checkpoint, Message(role=Role.ASSISTANT, content=INTERRUPTED)])
