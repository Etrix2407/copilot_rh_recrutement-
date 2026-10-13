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
    assert "CV de Jean" in message.content
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
