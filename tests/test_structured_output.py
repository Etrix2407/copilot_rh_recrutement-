"""Appel au LLM avec réponse JSON validée et une seule relance (sans réseau, faux LLM)."""

import asyncio

import pytest
from pydantic import BaseModel

from app.llm.base import LLMError, Role
from app.services.structured_output import MAX_ATTEMPTS, InvalidLLMOutputError, generate_validated
from tests.fakes import FakeLLMClient


class Answer(BaseModel):
    value: int


def generate(fake_llm: FakeLLMClient) -> Answer:
    return asyncio.run(generate_validated(fake_llm, "Question", system="Système", schema=Answer, temperature=0.0))


def test_valid_first_answer_needs_a_single_call(fake_llm: FakeLLMClient) -> None:
    fake_llm.json_answers = ['{"value": 1}']

    assert generate(fake_llm) == Answer(value=1)
    assert len(fake_llm.json_calls) == 1


def test_invalid_answer_is_retried_once_with_the_error(fake_llm: FakeLLMClient) -> None:
    fake_llm.json_answers = ['{"value": "pas un nombre"}', '{"value": 2}']

    assert generate(fake_llm) == Answer(value=2)
    retry_messages = fake_llm.json_calls[1]["messages"]
    assert [message.role for message in retry_messages] == [Role.USER, Role.ASSISTANT, Role.USER]
    assert "ne respecte pas le schéma" in retry_messages[-1].content


def test_retry_is_sent_only_once(fake_llm: FakeLLMClient) -> None:
    # Une troisième réponse valide est prévue : elle ne doit jamais être demandée
    fake_llm.json_answers = ["{}", "{}", '{"value": 3}']

    with pytest.raises(InvalidLLMOutputError):
        generate(fake_llm)
    assert MAX_ATTEMPTS == 2
    assert len(fake_llm.json_calls) == MAX_ATTEMPTS


def test_llm_error_during_the_retry_is_raised(fake_llm: FakeLLMClient) -> None:
    fake_llm.json_answers = ["{}", LLMError("quota dépassé")]

    with pytest.raises(LLMError, match="quota dépassé"):
        generate(fake_llm)
    assert len(fake_llm.json_calls) == 2
