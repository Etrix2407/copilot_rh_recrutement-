import asyncio

import pytest

from app.data.job_offers import PYTHON_DEV_JOB_OFFER
from app.llm.base import Role
from app.models.candidate import CandidateStatus
from app.models.cv_analysis import CVAnalysis
from app.services.candidate_store import CandidateStore
from app.services.cv_parser import UNNAMED_CANDIDATE, analyze_candidate, parse_cv
from app.services.structured_output import InvalidLLMOutputError
from tests.fakes import FakeLLMClient

INVALID_JSON = '{"match_score": 150}'


def test_valid_answer_needs_a_single_call(fake_llm: FakeLLMClient, valid_analysis_json: str) -> None:
    fake_llm.json_answers = [valid_analysis_json]

    analysis = asyncio.run(parse_cv(fake_llm, "CV de Jean"))

    assert analysis.match_score == 90
    [call] = fake_llm.json_calls
    assert call["temperature"] == 0.0
    assert call["schema"] is CVAnalysis
    [message] = call["messages"]
    # Le CV est délimité comme une donnée : le prompt système s'appuie sur ces balises
    assert "<cv>\nCV de Jean\n</cv>" in message.content
    assert PYTHON_DEV_JOB_OFFER.strip() in message.content


def test_invalid_answer_is_retried_with_the_error(fake_llm: FakeLLMClient, valid_analysis_json: str) -> None:
    fake_llm.json_answers = [INVALID_JSON, valid_analysis_json]

    analysis = asyncio.run(parse_cv(fake_llm, "CV de Jean"))

    assert analysis.match_score == 90
    retry_messages = fake_llm.json_calls[1]["messages"]
    assert [message.role for message in retry_messages] == [Role.USER, Role.ASSISTANT, Role.USER]
    assert retry_messages[1].content == INVALID_JSON
    assert "match_score" in retry_messages[2].content


def test_gives_up_after_two_calls(fake_llm: FakeLLMClient) -> None:
    fake_llm.json_answers = [INVALID_JSON, INVALID_JSON]

    with pytest.raises(InvalidLLMOutputError):
        asyncio.run(parse_cv(fake_llm, "CV de Jean"))

    assert len(fake_llm.json_calls) == 2


def test_analyze_candidate_registers_an_analyzed_candidate(
    fake_llm: FakeLLMClient, valid_analysis_json: str
) -> None:
    fake_llm.json_answers = [valid_analysis_json]
    store = CandidateStore()

    candidate = asyncio.run(analyze_candidate("CV de Jean", llm=fake_llm, store=store))

    assert candidate.name == "Jean Dupont"
    assert candidate.status is CandidateStatus.ANALYZED
    assert candidate.analysis is not None
    assert store.get(candidate.id) == candidate


def test_candidate_without_name_gets_a_placeholder(fake_llm: FakeLLMClient) -> None:
    fake_llm.json_answers = [
        CVAnalysis(
            candidate_name=None,
            email=None,
            key_skills=[],
            years_of_experience=None,
            education_level=None,
            match_score=10,
            score_justifications=["CV quasi vide."],
            red_flags=[],
        ).model_dump_json()
    ]

    candidate = asyncio.run(analyze_candidate("???", llm=fake_llm, store=CandidateStore()))

    assert candidate.name == UNNAMED_CANDIDATE


def test_reanalysis_of_a_known_email_updates_the_same_candidate(
    fake_llm: FakeLLMClient, valid_analysis_json: str
) -> None:
    store = CandidateStore()
    fake_llm.json_answers = [valid_analysis_json, valid_analysis_json]

    first = asyncio.run(analyze_candidate("CV de Jean", llm=fake_llm, store=store))
    second = asyncio.run(analyze_candidate("CV de Jean, version 2", llm=fake_llm, store=store))

    assert second.id == first.id
    assert len(store.list_all()) == 1


def analysis_json(name: str | None, email: str | None) -> str:
    return CVAnalysis(
        candidate_name=name,
        email=email,
        key_skills=["Python"],
        years_of_experience=3,
        education_level=None,
        match_score=50,
        score_justifications=["Profil moyen."],
        red_flags=[],
    ).model_dump_json()


def test_shared_email_with_another_name_creates_a_new_candidate(fake_llm: FakeLLMClient) -> None:
    store = CandidateStore()
    fake_llm.json_answers = [
        analysis_json("Alice Martin", "contact@famille.fr"),
        analysis_json("Bob Martin", "contact@famille.fr"),
    ]

    alice = asyncio.run(analyze_candidate("CV d'Alice", llm=fake_llm, store=store))
    bob = asyncio.run(analyze_candidate("CV de Bob", llm=fake_llm, store=store))

    assert bob.id != alice.id
    assert store.get(alice.id).name == "Alice Martin"


@pytest.mark.parametrize("email", [None, "Non renseigné", "   "])
def test_missing_or_invalid_email_never_merges(fake_llm: FakeLLMClient, email: str | None) -> None:
    store = CandidateStore()
    fake_llm.json_answers = [analysis_json("Claire Durand", email), analysis_json("Claire Durand", email)]

    first = asyncio.run(analyze_candidate("CV 1", llm=fake_llm, store=store))
    second = asyncio.run(analyze_candidate("CV 2", llm=fake_llm, store=store))

    assert first.id != second.id
    assert first.email is None


def test_too_long_name_is_truncated_instead_of_failing(fake_llm: FakeLLMClient) -> None:
    fake_llm.json_answers = [analysis_json("Jean " + "x" * 300, None)]

    candidate = asyncio.run(analyze_candidate("CV", llm=fake_llm, store=CandidateStore()))

    assert len(candidate.name) == 100
