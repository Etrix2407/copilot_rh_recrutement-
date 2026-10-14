"""Conversations avec l'agent : historique en mémoire et flux d'événements pour le chat."""

import contextlib
import datetime
import logging
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Sequence

from app.llm.base import LLMClient, LLMError, Message, Role
from app.messages import LLM_UNAVAILABLE
from app.models.agent import AgentEvent, DoneEvent, ErrorEvent, StartEvent
from app.services.agent import AgentCheckpoint, AgentReply, stream_agent
from app.services.candidate_store import CandidateStore

logger = logging.getLogger(__name__)

UNEXPECTED_ERROR = "Une erreur inattendue est survenue. Réessayez ou reformulez votre demande."
# Clôt l'historique d'une réponse interrompue (erreur, déconnexion), avec ou sans outils exécutés
INTERRUPTED = "(Réponse interrompue.)"
CONVERSATION_TOO_LONG = "Cette conversation est trop longue. Commencez une nouvelle conversation."
CONVERSATION_BUSY = "Une réponse est déjà en cours pour cette conversation."

# Plafonds mémoire : au-delà, les plus anciennes conversations sont oubliées
MAX_CONVERSATIONS = 100
# Taille d'historique (appels et résultats d'outils compris) au-delà de laquelle une conversation
# n'accepte plus de nouvelle demande : tout l'historique est renvoyé au LLM à chaque tour
MAX_HISTORY_MESSAGES = 60
# Durée maximale d'occupation d'une conversation par un tour : libère une conversation dont le flux
# n'a jamais été lu (client déconnecté avant le premier événement : le finally de chat() ne s'exécute pas)
TURN_TIMEOUT_SECONDS = 120.0


class ConversationNotFoundError(Exception):
    def __init__(self, conversation_id: str) -> None:
        super().__init__("Cette conversation n'existe pas ou a expiré.")
        self.conversation_id = conversation_id


class ConversationTooLongError(Exception):
    def __init__(self) -> None:
        super().__init__(CONVERSATION_TOO_LONG)


class ConversationStore:
    """Historiques des conversations en mémoire : ils sont vidés à chaque redémarrage de l'API.

    Suit aussi les tours en cours (un seul par conversation, identifié par un jeton) et le nombre
    d'effacements RGPD : un tour commencé avant un effacement n'est pas enregistré.
    """

    def __init__(
        self, max_conversations: int = MAX_CONVERSATIONS, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._conversations: OrderedDict[str, list[Message]] = OrderedDict()
        self._max_conversations = max_conversations
        self._clock = clock
        # Conversations occupées par un tour : id -> (jeton du tour, instant où l'occupation expire)
        self._busy: dict[str, tuple[str, float]] = {}
        self._erasure_count = 0

    @property
    def erasure_count(self) -> int:
        """Nombre d'effacements effectués : à noter au début d'un tour, puis à passer à save()."""
        return self._erasure_count

    def open(self, conversation_id: str | None) -> tuple[str, list[Message]]:
        """Renvoie l'id et l'historique de la conversation à poursuivre ; sans id, en démarre une nouvelle.

        Une nouvelle conversation dont le premier tour est en cours est connue (historique vide) :
        son id, envoyé par l'événement start, mène alors à un refus « occupée », pas « inconnue ».
        Lève ConversationNotFoundError si l'id est inconnu, ConversationTooLongError si
        l'historique est trop long pour une nouvelle demande.
        """
        if conversation_id is None:
            return uuid.uuid4().hex, []
        if conversation_id in self._conversations:
            history = list(self._conversations[conversation_id])
        elif self._is_busy(conversation_id):
            history = []
        else:
            raise ConversationNotFoundError(conversation_id)
        if len(history) >= MAX_HISTORY_MESSAGES:
            raise ConversationTooLongError
        return conversation_id, history

    def start_turn(self, conversation_id: str) -> str | None:
        """Marque la conversation comme occupée ; renvoie le jeton du tour, ou None si un tour y est déjà en cours.

        L'occupation expire après TURN_TIMEOUT_SECONDS, au cas où end_turn ne serait jamais appelé.
        """
        if self._is_busy(conversation_id):
            return None
        token = uuid.uuid4().hex
        self._busy[conversation_id] = (token, self._clock() + TURN_TIMEOUT_SECONDS)
        return token

    def end_turn(self, conversation_id: str, token: str) -> None:
        """Libère la conversation si ce tour l'occupe encore.

        Un tour dont l'occupation a expiré ne libère pas le tour suivant, qui a un autre jeton.
        """
        if self._busy.get(conversation_id, (None,))[0] == token:
            del self._busy[conversation_id]

    def save(self, conversation_id: str, messages: Sequence[Message], *, erasures_seen: int | None = None) -> bool:
        """Enregistre l'historique ; renvoie False s'il n'est pas enregistré à cause d'un effacement.

        erasures_seen : valeur d'erasure_count au début du tour. Si un effacement a eu lieu depuis,
        rien n'est enregistré : la conversation a été oubliée et le reste.
        """
        if erasures_seen is not None and erasures_seen != self._erasure_count:
            self._conversations.pop(conversation_id, None)
            return False
        self._conversations[conversation_id] = list(messages)
        self._conversations.move_to_end(conversation_id)
        while len(self._conversations) > self._max_conversations:
            self._conversations.popitem(last=False)
        return True

    def forget_all(self) -> int:
        """Oublie toutes les conversations, y compris celles des tours en cours (voir save).

        Utilisé pour l'effacement d'un candidat (RGPD) : chercher son nom dans les conversations
        manquerait « M. Dupont », « DUPONT Jean » ou une faute de frappe ; tout oublier est simple,
        sûr et honnête. Renvoie le nombre de conversations oubliées.
        """
        self._erasure_count += 1
        forgotten = len(self._conversations)
        self._conversations.clear()
        return forgotten

    def _is_busy(self, conversation_id: str) -> bool:
        """Vrai si un tour non expiré occupe la conversation ; oublie au passage les occupations expirées."""
        now = self._clock()
        self._busy = {key: busy for key, busy in self._busy.items() if busy[1] > now}
        return conversation_id in self._busy


async def chat(
    message: str,
    *,
    conversation_id: str,
    history: Sequence[Message],
    llm: LLMClient,
    store: CandidateStore,
    conversations: ConversationStore,
    today: datetime.date | None = None,
    erasures_seen: int | None = None,
    turn_token: str | None = None,
) -> AsyncIterator[AgentEvent]:
    """Produit start, les événements de la réponse de l'agent, puis done ou error.

    L'événement start transmet l'id de la conversation dès le début : le client peut la
    poursuivre même si la réponse est interrompue (erreur, bouton « Arrêter », coupure).
    L'historique complet est enregistré à la fin de la réponse. Si elle est interrompue,
    la conversation est quand même enregistrée (l'id est déjà connu du client), close par
    INTERRUPTED : jusqu'au dernier outil exécuté (une réservation déjà faite reste connue
    au tour suivant), sinon avec le seul message de l'utilisateur.

    erasures_seen : nombre d'effacements RGPD connus à l'ouverture de la conversation (par défaut,
    au début du tour). Si un candidat a été effacé depuis, rien n'est enregistré.
    turn_token : jeton renvoyé par start_turn ; la conversation est alors libérée (end_turn) à
    la fin du tour, quelle qu'en soit l'issue. La longueur de l'historique est contrôlée avant,
    par ConversationStore.open.
    """
    if erasures_seen is None:
        erasures_seen = conversations.erasure_count
    try:
        yield StartEvent(conversation_id=conversation_id)
        # Historique à enregistrer si la réponse n'aboutit pas ; remplacé à chaque point de reprise
        partial: list[Message] = [*history, Message(role=Role.USER, content=message)]
        finished = False
        try:
            # aclosing : une déconnexion ferme tout de suite l'agent et le flux du LLM
            async with contextlib.aclosing(
                stream_agent(message, history=history, llm=llm, store=store, today=today)
            ) as events:
                async for item in events:
                    if isinstance(item, AgentCheckpoint):
                        partial = item.messages
                    elif isinstance(item, AgentReply):
                        conversations.save(conversation_id, item.messages, erasures_seen=erasures_seen)
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
            if not finished:
                conversations.save(
                    conversation_id,
                    [*partial, Message(role=Role.ASSISTANT, content=INTERRUPTED)],
                    erasures_seen=erasures_seen,
                )
    finally:
        if turn_token is not None:
            conversations.end_turn(conversation_id, turn_token)
