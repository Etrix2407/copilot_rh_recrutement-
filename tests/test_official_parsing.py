"""Test officiel n°1 et robustesse du parsing, avec le vrai LLM configuré dans .env.

Ces tests consomment du quota : ils ne tournent qu'avec `pytest -m llm`.
"""

import asyncio
import re
from pathlib import Path

import pytest

from app.config import get_settings
from app.data.candidates import SAMPLE_CANDIDATE_1, SAMPLE_CANDIDATE_2
from app.llm.base import LLMClient
from app.llm.factory import create_llm_client
from app.models.cv_analysis import CVAnalysis
from app.services.cv_parser import parse_cv

pytestmark = pytest.mark.llm

ATYPICAL_CVS_DIR = Path(__file__).parent / "fixtures" / "cvs"


@pytest.fixture
def real_llm() -> LLMClient:
    # Un client par test : son client HTTP asynchrone reste lié à la boucle du premier asyncio.run
    return create_llm_client(get_settings())


def has_skill(analysis: CVAnalysis, pattern: str) -> bool:
    return any(re.search(pattern, skill, flags=re.IGNORECASE) for skill in analysis.key_skills)


def test_jean_dupont_is_a_strong_match(real_llm: LLMClient) -> None:
    analysis = asyncio.run(parse_cv(real_llm, SAMPLE_CANDIDATE_1))

    assert analysis.match_score > 80
    assert has_skill(analysis, r"fastapi")
    assert has_skill(analysis, r"\bRAG\b")


def test_sophie_martin_is_a_weak_match(real_llm: LLMClient) -> None:
    analysis = asyncio.run(parse_cv(real_llm, SAMPLE_CANDIDATE_2))

    assert analysis.match_score < 40


@pytest.mark.parametrize("cv_path", sorted(ATYPICAL_CVS_DIR.glob("*.txt")), ids=lambda path: path.stem)
def test_atypical_cv_produces_a_valid_analysis(real_llm: LLMClient, cv_path: Path) -> None:
    # parse_cv ne renvoie qu'une analyse validée par Pydantic : obtenir un résultat suffit
    analysis = asyncio.run(parse_cv(real_llm, cv_path.read_text(encoding="utf-8")))

    assert 0 <= analysis.match_score <= 100
