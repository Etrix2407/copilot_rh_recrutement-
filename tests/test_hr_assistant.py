import asyncio
import json

import pytest

from app.data.hr_policies import HR_POLICIES
from app.models.hr_assistant import HRAnswerDraft
from app.services.hr_assistant import REFUSAL, TOP_K, ask_hr_policies
from app.services.policy_index import PolicyIndex
from tests.fakes import FakeLLMClient

RTT_QUESTION = "Combien de jours de RTT ai-je droit et puis-je les placer sur un CET ?"


def draft(*, answered: bool, answer: str = "", source_ids: list[str] | None = None) -> str:
    return json.dumps({"answered": answered, "answer": answer, "source_ids": source_ids or []})


@pytest.fixture
def indexed(policy_index: PolicyIndex) -> PolicyIndex:
    policy_index.index(HR_POLICIES)
    return policy_index


def test_answer_keeps_only_the_sources_used(fake_llm: FakeLLMClient, indexed: PolicyIndex) -> None:
    fake_llm.json_answers = [draft(answered=True, answer="10 RTT par an.", source_ids=["rh_doc_02"])]

    result = asyncio.run(ask_hr_policies(RTT_QUESTION, llm=fake_llm, index=indexed))

    assert result.answer == "10 RTT par an."
    assert [source.id for source in result.sources] == ["rh_doc_02"]


def test_llm_receives_question_and_retrieved_excerpts(fake_llm: FakeLLMClient, indexed: PolicyIndex) -> None:
    fake_llm.json_answers = [draft(answered=False)]

    asyncio.run(ask_hr_policies(RTT_QUESTION, llm=fake_llm, index=indexed))

    [call] = fake_llm.json_calls
    [message] = call["messages"]
    # La question est délimitée comme une donnée : le prompt système s'appuie sur ces balises
    assert f"<question>\n{RTT_QUESTION}\n</question>" in message.content
    assert message.content.count("[rh_doc_") == TOP_K
    assert call["temperature"] == 0.0
    assert call["schema"] is HRAnswerDraft


def test_unanswered_question_returns_the_exact_refusal(fake_llm: FakeLLMClient, indexed: PolicyIndex) -> None:
    fake_llm.json_answers = [draft(answered=False, answer="Il n'y a pas de prime.")]

    result = asyncio.run(ask_hr_policies("Quelle est la prime de naissance ?", llm=fake_llm, index=indexed))

    assert result.answer == REFUSAL
    assert result.sources == []


@pytest.mark.parametrize("source_ids", [[], ["rh_doc_99"]], ids=["no_source", "unknown_source"])
def test_answer_without_valid_source_is_refused(
    fake_llm: FakeLLMClient, indexed: PolicyIndex, source_ids: list[str]
) -> None:
    fake_llm.json_answers = [draft(answered=True, answer="Une prime de 500 €.", source_ids=source_ids)]

    result = asyncio.run(ask_hr_policies("Quelle est la prime de naissance ?", llm=fake_llm, index=indexed))

    assert result.answer == REFUSAL
    assert result.sources == []


@pytest.mark.parametrize("answer", ["", "   "], ids=["empty", "blank"])
def test_empty_answer_is_refused_even_if_answered(fake_llm: FakeLLMClient, indexed: PolicyIndex, answer: str) -> None:
    fake_llm.json_answers = [draft(answered=True, answer=answer, source_ids=["rh_doc_02"])]

    result = asyncio.run(ask_hr_policies(RTT_QUESTION, llm=fake_llm, index=indexed))

    assert result.answer == REFUSAL
    assert result.sources == []
