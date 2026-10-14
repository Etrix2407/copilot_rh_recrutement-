"""Test officiel n°2 et étanchéité du RAG, avec le vrai LLM et le vrai modèle d'embedding.

Ces tests consomment du quota : ils ne tournent qu'avec `pytest -m llm`.
"""

import re
from pathlib import Path

import chromadb
import pytest
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings
from app.data.hr_policies import HR_POLICIES
from app.models.hr_assistant import HRAnswer
from app.services.hr_assistant import REFUSAL, ask_hr_policies
from app.services.policy_index import PolicyIndex, create_embedding_function
from tests.real_llm import run_with_real_llm

pytestmark = pytest.mark.llm

# Règles plausibles mais absentes des politiques, dont des cas presque couverts et une injection
TRAP_QUESTIONS_PATH = Path(__file__).parent / "fixtures" / "rag_trap_questions.txt"
TRAP_QUESTIONS = TRAP_QUESTIONS_PATH.read_text(encoding="utf-8").splitlines()


@pytest.fixture(scope="module")
def real_index(tmp_path_factory: pytest.TempPathFactory) -> PolicyIndex:
    path = tmp_path_factory.mktemp("chroma")
    chroma = chromadb.PersistentClient(path=str(path), settings=ChromaSettings(anonymized_telemetry=False))
    index = PolicyIndex(chroma, create_embedding_function(get_settings().embedding_model))
    index.index(HR_POLICIES)
    return index


def ask(question: str, index: PolicyIndex) -> HRAnswer:
    return run_with_real_llm(lambda llm: ask_hr_policies(question, llm=llm, index=index))


def test_rtt_and_cet_question_is_answered_with_its_source(real_index: PolicyIndex) -> None:
    result = ask("Combien de jours de RTT ai-je droit et puis-je les placer sur un CET ?", real_index)

    # Mots entiers : « 5 » ne doit pas être trouvé dans « 25 jours de congés »
    assert re.search(r"\b10\b", result.answer)
    assert re.search(r"\b5\b", result.answer)
    assert "CET" in result.answer or "Compte Épargne Temps" in result.answer
    assert "rh_doc_02" in [source.id for source in result.sources]


def test_documented_question_is_not_refused(real_index: PolicyIndex) -> None:
    # Contrôle : l'étanchéité ne doit pas transformer l'assistant en machine à refuser
    result = ask("Quel est le budget formation annuel par salarié ?", real_index)

    assert "1 500" in result.answer or "1500" in result.answer
    assert "rh_doc_03" in [source.id for source in result.sources]


@pytest.mark.parametrize("question", TRAP_QUESTIONS)
def test_undocumented_question_is_refused(real_index: PolicyIndex, question: str) -> None:
    result = ask(question, real_index)

    assert result.answer == REFUSAL
    assert result.sources == []
