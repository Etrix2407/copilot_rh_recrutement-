"""Agent de qualification : boucle de tool calling (pilier 3), en streaming (pilier 4).

Protection contre l'injection de prompt : les règles importantes ne reposent pas
sur le seul prompt système, que le LLM peut ignorer. Les garde-fous (outils connus,
arguments validés, recherche avant réservation, dossier du candidat vérifié avant de
prendre un créneau) sont appliqués par app/services/agent_tools.py, et le store
contrôle les transitions de statut.
"""

import datetime
import logging
import re
from collections.abc import AsyncIterator, Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.llm.base import LLMClient, LLMError, Message, Role, ToolResult
from app.models.agent import TokenEvent, ToolResultEvent, ToolStartEvent
from app.prompts import load_prompt
from app.services.agent_tools import is_successful_booking, run_tool, searched_dates_in, summarize
from app.services.candidate_store import CandidateStore
from app.tools.definitions import TOOL_DEFINITIONS

logger = logging.getLogger(__name__)

# Au-delà, l'agent s'arrête : protège contre les boucles d'outils sans fin
MAX_ITERATIONS = 8
AGENT_TEMPERATURE = 0.0

ITERATION_LIMIT_ANSWER = (
    "Je n'ai pas réussi à terminer cette demande en un nombre raisonnable d'étapes. "
    "Pouvez-vous la reformuler ou la découper ?"
)

EMPTY_ANSWER = "Je n'ai pas de réponse à proposer. Pouvez-vous reformuler votre demande ?"

SYSTEM_PROMPT = load_prompt("agent")


class AgentReply(BaseModel):
    """Réponse finale de l'agent et historique complet, à renvoyer au tour suivant."""

    model_config = ConfigDict(frozen=True)

    answer: str
    messages: list[Message] = Field(description="Historique de la conversation, appels d'outils compris")


class AgentCheckpoint(BaseModel):
    """Historique juste après l'exécution d'outils, à conserver si la réponse est ensuite interrompue.

    Une réservation déjà faite doit rester dans l'historique, sinon le LLM pourrait réserver à nouveau.
    """

    model_config = ConfigDict(frozen=True)

    messages: list[Message]


async def stream_agent(
    user_message: str,
    *,
    history: Sequence[Message] = (),
    llm: LLMClient,
    store: CandidateStore,
    today: datetime.date | None = None,
) -> AsyncIterator[TokenEvent | ToolStartEvent | ToolResultEvent | AgentCheckpoint | AgentReply]:
    """Traite un message et produit les événements au fil de l'eau, puis l'AgentReply en dernier.

    Le texte du LLM est découpé en mots (TokenEvent) ; chaque outil produit un
    ToolStartEvent, un ToolResultEvent puis un AgentCheckpoint.
    Lève LLMError si un appel au LLM échoue.
    """
    system = SYSTEM_PROMPT.format(today=(today or datetime.date.today()).isoformat())
    messages = [*history, Message(role=Role.USER, content=user_message)]
    bookings_done = 0

    for _ in range(MAX_ITERATIONS):
        reply: Message | None = None
        words = _WordBuffer()
        async for item in llm.stream_with_tools(
            messages, system=system, tools=TOOL_DEFINITIONS, temperature=AGENT_TEMPERATURE
        ):
            if isinstance(item, Message):
                reply = item
                continue
            for word in words.feed(item):
                yield TokenEvent(text=word)
        for word in words.flush():
            yield TokenEvent(text=word)
        if reply is None:
            raise LLMError("Le flux du LLM s'est terminé sans message final.")
        if not reply.tool_calls and not reply.content.strip():
            # Réponse vide (possible avec certains fournisseurs) : l'utilisateur doit quand même lire quelque chose
            reply = Message(role=Role.ASSISTANT, content=EMPTY_ANSWER)
            for word in _split_words(EMPTY_ANSWER):
                yield TokenEvent(text=word)
        if not reply.tool_calls:
            messages.append(reply)
            yield AgentReply(answer=reply.content, messages=messages)
            return

        # Calculé AVANT la série d'appels : une recherche de cette série n'autorise pas encore
        # la réservation, le LLM n'ayant pas vu son résultat
        searched_dates = searched_dates_in(messages)
        results: list[ToolResult] = []
        for call in reply.tool_calls:
            yield ToolStartEvent(name=call.name, arguments=call.arguments)
            result = run_tool(call, store=store, searched_dates=searched_dates, bookings_done=bookings_done)
            bookings_done += is_successful_booking(result)
            yield summarize(result)
            results.append(result)
            # Point de reprise après CHAQUE outil : une réservation déjà faite reste dans
            # l'historique même si la suite de la série échoue ou si le client se déconnecte
            yield AgentCheckpoint(messages=_with_results(messages, reply, results))
        messages = _with_results(messages, reply, results)

    logger.warning("Agent arrêté après %d itérations sans réponse finale", MAX_ITERATIONS)
    for word in _split_words(ITERATION_LIMIT_ANSWER):
        yield TokenEvent(text=word)
    # L'historique se termine par une réponse de l'assistant, comme après un tour normal
    messages.append(Message(role=Role.ASSISTANT, content=ITERATION_LIMIT_ANSWER))
    yield AgentReply(answer=ITERATION_LIMIT_ANSWER, messages=messages)


async def run_agent(
    user_message: str,
    *,
    history: Sequence[Message] = (),
    llm: LLMClient,
    store: CandidateStore,
    today: datetime.date | None = None,
) -> AgentReply:
    """Version sans streaming : renvoie seulement la réponse finale et l'historique."""
    async for item in stream_agent(user_message, history=history, llm=llm, store=store, today=today):
        if isinstance(item, AgentReply):
            return item
    raise AssertionError("stream_agent se termine toujours par un AgentReply")


def _with_results(messages: list[Message], reply: Message, results: list[ToolResult]) -> list[Message]:
    """Historique suivi des appels déjà exécutés de `reply` et de leurs résultats.

    Les appels pas encore exécutés sont retirés du message de l'assistant : Gemini exige
    autant de réponses de fonction que d'appels, un historique partiel resterait sinon inutilisable.
    """
    executed = reply.model_copy(update={"tool_calls": reply.tool_calls[: len(results)]})
    return [*messages, executed, Message(role=Role.TOOL, tool_results=list(results))]


class _WordBuffer:
    """Regroupe les morceaux du flux du LLM en mots entiers.

    Le fournisseur peut couper un morceau au milieu d'un mot : la fin incomplète attend le suivant.
    """

    def __init__(self) -> None:
        self._pending = ""

    def feed(self, chunk: str) -> list[str]:
        """Renvoie les mots complets ; garde la fin incomplète pour le morceau suivant."""
        words = _split_words(self._pending + chunk)
        self._pending = words.pop() if words and not words[-1][-1].isspace() else ""
        return words

    def flush(self) -> list[str]:
        """Renvoie le dernier mot en attente, à la fin du flux."""
        rest, self._pending = self._pending, ""
        return [rest] if rest else []


def _split_words(text: str) -> list[str]:
    """Découpe en mots, chacun avec les espaces qui le suivent : leur concaténation redonne le texte."""
    return re.findall(r"\s*\S+\s*", text) or ([text] if text else [])
