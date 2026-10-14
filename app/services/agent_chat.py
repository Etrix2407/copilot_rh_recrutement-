"""Conversations avec l'agent : historique en mémoire et flux d'événements pour le chat."""

import contextlib
import datetime
import json
import logging
import re
import time
import unicodedata
import uuid
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Callable, Iterable, Sequence

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
# Effacements RGPD retenus pour les tours en cours : au-delà, un tour plus ancien n'est pas enregistré
MAX_TRACKED_ERASURES = 100
# Durée maximale d'occupation d'une conversation par un tour : libère une conversation dont le flux
# n'a jamais été lu (client déconnecté avant le premier événement : le finally de chat() ne s'exécute pas)
TURN_TIMEOUT_SECONDS = 120.0


class ConversationNotFoundError(Exception):
    def __init__(self, conversation_id: str) -> None:
        super().__init__("Cette conversation n'existe pas ou a expiré.")
        self.conversation_id = conversation_id


class ConversationStore:
    """Historiques des conversations en mémoire : ils sont vidés à chaque redémarrage de l'API.

    Suit aussi les tours en cours (un seul par conversation) et les derniers effacements RGPD :
    un tour commencé avant un effacement ne doit pas réenregistrer la personne effacée.
    """

    def __init__(
        self, max_conversations: int = MAX_CONVERSATIONS, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._conversations: OrderedDict[str, list[Message]] = OrderedDict()
        self._max_conversations = max_conversations
        self._clock = clock
        # Conversations occupées par un tour : id -> instant où l'occupation expire
        self._busy: dict[str, float] = {}
        # Nombre d'effacements depuis le démarrage, et motifs recherchés par les derniers d'entre eux
        self._erasure_count = 0
        self._erasures: deque[tuple[int, list[re.Pattern[str]]]] = deque(maxlen=MAX_TRACKED_ERASURES)

    @property
    def erasure_count(self) -> int:
        """Nombre d'effacements effectués : à noter au début d'un tour, puis à passer à save()."""
        return self._erasure_count

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

    def start_turn(self, conversation_id: str) -> bool:
        """Marque la conversation comme occupée ; renvoie False si un tour y est déjà en cours.

        L'occupation expire après TURN_TIMEOUT_SECONDS, au cas où end_turn ne serait jamais appelé.
        """
        now = self._clock()
        self._busy = {key: expires for key, expires in self._busy.items() if expires > now}
        if conversation_id in self._busy:
            return False
        self._busy[conversation_id] = now + TURN_TIMEOUT_SECONDS
        return True

    def end_turn(self, conversation_id: str) -> None:
        """Libère la conversation (sans effet si elle n'était pas occupée)."""
        self._busy.pop(conversation_id, None)

    def save(self, conversation_id: str, messages: Sequence[Message], *, erasures_seen: int | None = None) -> bool:
        """Enregistre l'historique ; renvoie False s'il a été oublié à cause d'un effacement.

        erasures_seen : valeur d'erasure_count au début du tour. Si un effacement a eu lieu depuis
        et que les messages mentionnent la personne effacée, la conversation est oubliée au lieu
        d'être enregistrée.
        """
        if erasures_seen is not None and self._mentions_erased_since(erasures_seen, messages):
            self._conversations.pop(conversation_id, None)
            return False
        self._conversations[conversation_id] = list(messages)
        self._conversations.move_to_end(conversation_id)
        while len(self._conversations) > self._max_conversations:
            self._conversations.popitem(last=False)
        return True

    def forget_mentions(self, terms: Iterable[str]) -> int:
        """Oublie les conversations qui mentionnent l'un des termes (nom, email).

        La recherche porte sur des mots entiers (« Li » ne correspond pas à « libres »), sans tenir
        compte de la casse, des espaces multiples ni de la forme Unicode (NFC/NFD).
        Utilisé pour l'effacement d'un candidat (RGPD). Les termes sont retenus pour les tours en
        cours (voir save). Renvoie le nombre de conversations oubliées.
        """
        patterns = _mention_patterns(terms)
        if not patterns:
            return 0
        self._erasure_count += 1
        self._erasures.append((self._erasure_count, patterns))
        forgotten = [
            conversation_id
            for conversation_id, messages in self._conversations.items()
            if _mentions(patterns, messages)
        ]
        for conversation_id in forgotten:
            del self._conversations[conversation_id]
        return len(forgotten)

    def _mentions_erased_since(self, erasures_seen: int, messages: Sequence[Message]) -> bool:
        """Vrai si les messages mentionnent une personne effacée après erasures_seen."""
        if erasures_seen >= self._erasure_count:
            return False
        # Effacements trop anciens pour être encore retenus : par prudence, la conversation est oubliée
        if erasures_seen < self._erasure_count - len(self._erasures):
            return True
        recent = [pattern for number, patterns in self._erasures if number > erasures_seen for pattern in patterns]
        return _mentions(recent, messages)


def _mention_patterns(terms: Iterable[str]) -> list[re.Pattern[str]]:
    """Motifs « mot entier » des termes normalisés ; les termes vides sont ignorés."""
    return [re.compile(rf"(?<!\w){re.escape(_normalize(term))}(?!\w)") for term in terms if term and term.strip()]


def _mentions(patterns: Sequence[re.Pattern[str]], messages: Sequence[Message]) -> bool:
    """Vrai si l'un des motifs apparaît dans les messages (texte, arguments et résultats des outils)."""
    if not patterns:
        return False
    text = _searchable_text(messages)
    return any(pattern.search(text) for pattern in patterns)


def _normalize(text: str) -> str:
    """Texte comparable : forme Unicode NFC, espaces multiples réduits, casse ignorée."""
    return " ".join(unicodedata.normalize("NFC", text).split()).casefold()


def _searchable_text(messages: Sequence[Message]) -> str:
    """Texte, arguments des outils et résultats, normalisés.

    La signature des appels (octets opaques du fournisseur, pas forcément de l'UTF-8) est
    exclue : la sérialiser ferait échouer l'effacement.
    """
    parts: list[str] = []
    for message in messages:
        parts.append(message.content)
        parts.extend(json.dumps(call.arguments, ensure_ascii=False, default=str) for call in message.tool_calls)
        parts.extend(json.dumps(result.content, ensure_ascii=False, default=str) for result in message.tool_results)
    return _normalize("\n".join(parts))


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
) -> AsyncIterator[AgentEvent]:
    """Produit start, les événements de la réponse de l'agent, puis done ou error.

    L'événement start transmet l'id de la conversation dès le début : le client peut la
    poursuivre même si la réponse est interrompue (erreur, bouton « Arrêter », coupure).
    L'historique complet est enregistré à la fin de la réponse. Si elle est interrompue,
    la conversation est quand même enregistrée (l'id est déjà connu du client), close par
    INTERRUPTED : jusqu'au dernier outil exécuté (une réservation déjà faite reste connue
    au tour suivant), sinon avec le seul message de l'utilisateur.

    erasures_seen : nombre d'effacements RGPD connus à l'ouverture de la conversation (par défaut,
    au début du tour). Si une personne mentionnée a été effacée depuis, rien n'est enregistré.
    La conversation est libérée (end_turn) à la fin du tour, quelle qu'en soit l'issue.
    """
    if erasures_seen is None:
        erasures_seen = conversations.erasure_count
    try:
        yield StartEvent(conversation_id=conversation_id)
        if len(history) >= MAX_HISTORY_MESSAGES:
            yield ErrorEvent(message=CONVERSATION_TOO_LONG)
            return
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
        conversations.end_turn(conversation_id)
