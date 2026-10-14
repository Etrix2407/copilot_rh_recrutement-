import asyncio
from collections.abc import AsyncIterator, Callable

import pytest

from app.llm.base import LLMError, Message, Role, ToolCall
from app.models.agent import AgentEvent, DoneEvent, ErrorEvent, StartEvent, TokenEvent, ToolResultEvent
from app.services.agent_chat import (
    INTERRUPTED,
    MAX_HISTORY_MESSAGES,
    TURN_TIMEOUT_SECONDS,
    UNEXPECTED_ERROR,
    ConversationNotFoundError,
    ConversationStore,
    ConversationTooLongError,
    chat,
)
from app.services.candidate_store import CandidateStore
from app.services.privacy import erase_candidate
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


def test_answer_interrupted_before_any_tool_is_saved_with_user_message(fake_llm: FakeLLMClient) -> None:
    # L'id a déjà été envoyé par l'événement start : le tour suivant ne doit pas recevoir 404
    conversations = ConversationStore()
    fake_llm.tool_answers = [LLMError("quota")]

    events = run_chat(fake_llm, conversations, "conv-1")

    assert isinstance(events[-1], ErrorEvent)
    _, history = conversations.open("conv-1")
    assert history == [
        Message(role=Role.USER, content="Bonjour"),
        Message(role=Role.ASSISTANT, content=INTERRUPTED),
    ]


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


def test_too_long_conversation_cannot_be_continued() -> None:
    # Contrôlé à l'ouverture, avant le quota et le flux : l'API renvoie alors 409
    conversations = ConversationStore()
    conversations.save("long", [Message(role=Role.USER, content="…")] * MAX_HISTORY_MESSAGES)

    with pytest.raises(ConversationTooLongError):
        conversations.open("long")


def test_interrupted_answer_keeps_the_tools_already_run(fake_llm: FakeLLMClient) -> None:
    conversations = ConversationStore()
    search = ToolCall(id="1", name="rechercher_creneaux_entretien", arguments={"date": "2026-10-16"})
    fake_llm.tool_answers = [Message(role=Role.ASSISTANT, tool_calls=[search]), LLMError("quota")]

    events = run_chat(fake_llm, conversations, "conv-1")

    assert isinstance(events[-1], ErrorEvent)
    _, history = conversations.open("conv-1")
    assert [message.role for message in history] == [Role.USER, Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]
    assert history[-1].content == INTERRUPTED


def test_forget_all_erases_every_conversation() -> None:
    conversations = ConversationStore()
    conversations.save("a", [Message(role=Role.USER, content="Réserve Jean Dupont")])
    conversations.save("b", [Message(role=Role.USER, content="Bonjour")])

    assert conversations.forget_all() == 2
    for conversation_id in ("a", "b"):
        with pytest.raises(ConversationNotFoundError):
            conversations.open(conversation_id)


# --- Déconnexion du client pendant la réponse ---


def disconnect_after(fake_llm: FakeLLMClient, conversations: ConversationStore, stop_at: type) -> None:
    """Lit le flux du chat jusqu'au premier événement stop_at (de la réservation, pour un résultat
    d'outil), puis ferme le flux comme le fait une déconnexion du client."""

    async def run() -> None:
        stream = chat(
            "Réserve Jean Dupont",
            conversation_id="conv-1",
            history=[],
            llm=fake_llm,
            store=CandidateStore(),
            conversations=conversations,
        )
        async for event in stream:
            if isinstance(event, stop_at) and getattr(event, "name", "reserver_entretien") == "reserver_entretien":
                break
        await stream.aclose()

    asyncio.run(run())


def test_disconnect_right_after_booking_result_keeps_the_booking(fake_llm: FakeLLMClient) -> None:
    conversations = ConversationStore()
    search = ToolCall(id="1", name="rechercher_creneaux_entretien", arguments={"date": "2026-10-15"})
    book = ToolCall(
        id="2",
        name="reserver_entretien",
        arguments={"candidat_nom": "Jean Dupont", "date": "2026-10-15", "heure": "09:00", "email": "j@d.fr"},
    )
    fake_llm.tool_answers = [
        Message(role=Role.ASSISTANT, tool_calls=[search]),
        Message(role=Role.ASSISTANT, tool_calls=[book]),
    ]

    disconnect_after(fake_llm, conversations, ToolResultEvent)

    _, history = conversations.open("conv-1")
    booked = [result.content for message in history for result in message.tool_results if result.call_id == "2"]
    assert booked and booked[0]["statut"] == "SUCCES"
    assert history[-1] == Message(role=Role.ASSISTANT, content=INTERRUPTED)


def test_disconnect_before_any_tool_saves_the_user_message(fake_llm: FakeLLMClient) -> None:
    conversations = ConversationStore()
    fake_llm.chunk_size = 3
    fake_llm.tool_answers = [Message(role=Role.ASSISTANT, content="Bonjour, je cherche les créneaux.")]

    disconnect_after(fake_llm, conversations, TokenEvent)

    _, history = conversations.open("conv-1")
    assert [message.content for message in history] == ["Réserve Jean Dupont", INTERRUPTED]


class ClosableLLM(FakeLLMClient):
    """Faux LLM dont le flux note sa fermeture."""

    def __init__(self) -> None:
        super().__init__()
        self.stream_closed = False

    async def stream_with_tools(self, *args: object, **kwargs: object) -> AsyncIterator[str | Message]:
        try:
            yield "Bonjour "
            yield "à "
            yield Message(role=Role.ASSISTANT, content="Bonjour à vous")
        finally:
            self.stream_closed = True


def test_disconnect_closes_the_llm_stream_immediately() -> None:
    llm = ClosableLLM()

    async def run() -> bool:
        stream = chat(
            "Bonjour",
            conversation_id="conv-1",
            history=[],
            llm=llm,
            store=CandidateStore(),
            conversations=ConversationStore(),
        )
        async for event in stream:
            if isinstance(event, TokenEvent):
                break
        await stream.aclose()
        # Vérifié avant la fin de la boucle : la fermeture ne doit pas attendre le ramasse-miettes
        return llm.stream_closed

    assert asyncio.run(run()) is True


# --- Effacement RGPD : toutes les conversations sont oubliées ---


@pytest.mark.parametrize("mention", ["M. Dupont", "DUPONT Jean", "Jean-Pierre D.", "le candidat de ce matin"])
def test_erase_candidate_forgets_conversations_whatever_the_wording(mention: str) -> None:
    # Une recherche du nom raterait ces formulations : tout est oublié
    store = CandidateStore()
    candidate = store.add(name="Jean Dupont", email="jean.dupont@email.com")
    conversations = ConversationStore()
    conversations.save("a", [Message(role=Role.USER, content=f"Réserve {mention}")])

    erase_candidate(candidate.id, store=store, conversations=conversations)

    with pytest.raises(ConversationNotFoundError):
        conversations.open("a")


# --- Effacement RGPD pendant un tour en cours ---


def chat_with_erasure_midway(
    fake_llm: FakeLLMClient,
    conversations: ConversationStore,
    erase: Callable[[], object],
    *,
    conversation_id: str = "conv-1",
    disconnect: bool = False,
) -> None:
    """Lance un tour sur Jean Dupont et appelle erase au premier morceau de texte, puis termine le
    tour normalement, ou ferme le flux comme une déconnexion du client si disconnect est vrai."""
    fake_llm.chunk_size = 3
    fake_llm.tool_answers = [Message(role=Role.ASSISTANT, content="Je cherche pour Jean Dupont.")]

    async def run() -> None:
        stream = chat(
            "Réserve Jean Dupont",
            conversation_id=conversation_id,
            history=[],
            llm=fake_llm,
            store=CandidateStore(),
            conversations=conversations,
        )
        erased = False
        async for event in stream:
            if isinstance(event, TokenEvent) and not erased:
                erase()
                erased = True
                if disconnect:
                    break
        await stream.aclose()

    asyncio.run(run())


def erase_jean_dupont(conversations: ConversationStore) -> Callable[[], None]:
    store = CandidateStore()
    candidate = store.add(name="Jean Dupont", email="jean.dupont@email.com")
    return lambda: erase_candidate(candidate.id, store=store, conversations=conversations)


@pytest.mark.parametrize("disconnect", [False, True], ids=["fin_normale", "deconnexion"])
def test_erasure_during_turn_is_not_undone_by_the_save(fake_llm: FakeLLMClient, disconnect: bool) -> None:
    conversations = ConversationStore()

    chat_with_erasure_midway(fake_llm, conversations, erase_jean_dupont(conversations), disconnect=disconnect)

    with pytest.raises(ConversationNotFoundError):
        conversations.open("conv-1")


def test_any_turn_in_progress_is_not_saved_after_erasure(fake_llm: FakeLLMClient) -> None:
    # Même une conversation qui ne cite pas la candidate effacée : elle pourrait la désigner autrement
    conversations = ConversationStore()
    store = CandidateStore()
    sophie = store.add(name="Sophie Martin", email=None)

    chat_with_erasure_midway(
        fake_llm, conversations, lambda: erase_candidate(sophie.id, store=store, conversations=conversations)
    )

    with pytest.raises(ConversationNotFoundError):
        conversations.open("conv-1")


def test_conversation_started_after_erasure_is_saved(fake_llm: FakeLLMClient) -> None:
    conversations = ConversationStore()
    erase_jean_dupont(conversations)()
    fake_llm.tool_answers = [Message(role=Role.ASSISTANT, content="Jean Dupont n'existe plus.")]

    run_chat(fake_llm, conversations, "conv-2")

    assert conversations.open("conv-2")[1]


# --- Un seul tour à la fois par conversation ---


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_conversation_accepts_one_turn_at_a_time() -> None:
    conversations = ConversationStore()

    token = conversations.start_turn("conv-1")
    assert token
    assert conversations.start_turn("conv-1") is None
    # Une autre conversation n'est pas concernée, et chaque tour a son propre jeton
    other = conversations.start_turn("conv-2")
    assert other and other != token


def test_turn_is_released_at_the_end_of_chat(fake_llm: FakeLLMClient) -> None:
    conversations = ConversationStore()
    token = conversations.start_turn("conv-1")
    fake_llm.tool_answers = [Message(role=Role.ASSISTANT, content="Salut")]

    async def consume() -> None:
        stream = chat(
            "Bonjour",
            conversation_id="conv-1",
            history=[],
            llm=fake_llm,
            store=CandidateStore(),
            conversations=conversations,
            turn_token=token,
        )
        _ = [event async for event in stream]

    asyncio.run(consume())

    assert conversations.start_turn("conv-1") is not None


def test_turn_expires_when_never_released() -> None:
    clock = FakeClock()
    conversations = ConversationStore(clock=clock)
    conversations.start_turn("conv-1")

    clock.now = TURN_TIMEOUT_SECONDS - 1
    assert conversations.start_turn("conv-1") is None
    clock.now = TURN_TIMEOUT_SECONDS
    assert conversations.start_turn("conv-1") is not None


def test_expired_turn_does_not_release_the_next_one() -> None:
    # Le premier tour a dépassé l'expiration ; quand il se termine enfin, le tour suivant reste protégé
    clock = FakeClock()
    conversations = ConversationStore(clock=clock)
    late_token = conversations.start_turn("conv-1")
    clock.now = TURN_TIMEOUT_SECONDS
    assert conversations.start_turn("conv-1") is not None

    conversations.end_turn("conv-1", late_token)

    assert conversations.start_turn("conv-1") is None


def test_new_conversation_is_known_while_its_first_turn_runs() -> None:
    # L'id reçu dans start pendant le premier tour désigne une conversation occupée, pas inconnue
    conversations = ConversationStore()
    conversation_id, _ = conversations.open(None)
    conversations.start_turn(conversation_id)

    assert conversations.open(conversation_id) == (conversation_id, [])
    assert conversations.start_turn(conversation_id) is None
