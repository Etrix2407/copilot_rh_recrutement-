"""Test officiel n°3 : l'agent recherche puis réserve un créneau, avec le vrai LLM.

Ces tests consomment du quota : ils ne tournent qu'avec `pytest -m llm`.
"""

import pytest

from app.data.agenda import RECRUITER_AGENDA
from app.services.agent import AgentReply, run_agent
from app.services.candidate_store import CandidateStore
from tests.real_llm import run_with_real_llm

pytestmark = [pytest.mark.llm, pytest.mark.usefixtures("restore_agenda")]

OFFICIAL_REQUEST = (
    "Trouve-moi un créneau le 2026-10-15 pour réserver un entretien avec Jean Dupont (jean.dupont@email.com)"
)


def ask_agent(message: str, store: CandidateStore) -> AgentReply:
    return run_with_real_llm(lambda llm: run_agent(message, llm=llm, store=store))


def tool_names(reply: AgentReply) -> list[str]:
    return [call.name for message in reply.messages for call in message.tool_calls]


def test_official_request_searches_then_books() -> None:
    reply = ask_agent(OFFICIAL_REQUEST, CandidateStore())

    names = tool_names(reply)
    assert "book_interview" in names
    assert names.index("search_interview_slots") < names.index("book_interview")
    assert len(RECRUITER_AGENDA["2026-10-15"]) == 3
    assert reply.answer


def test_second_identical_request_books_another_slot() -> None:
    store = CandidateStore()

    ask_agent(OFFICIAL_REQUEST, store)
    ask_agent(OFFICIAL_REQUEST, store)

    assert len(RECRUITER_AGENDA["2026-10-15"]) == 2


def test_known_candidate_is_scheduled() -> None:
    store = CandidateStore()
    candidate = store.add(name="Jean Dupont", email="jean.dupont@email.com")
    store.update_status(candidate.id, "analyzed")

    ask_agent(OFFICIAL_REQUEST, store)

    assert store.get(candidate.id).status == "interview_scheduled"
