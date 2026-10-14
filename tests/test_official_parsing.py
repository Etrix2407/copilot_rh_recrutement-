"""Test officiel n°1 et robustesse du parsing, avec le vrai LLM configuré dans .env.

Ces tests consomment du quota : ils ne tournent qu'avec `pytest -m llm`.
"""

import re
from pathlib import Path

import pytest

from app.data.candidates import SAMPLE_CANDIDATE_1, SAMPLE_CANDIDATE_2
from app.models.cv_analysis import CVAnalysis
from app.services.cv_parser import parse_cv
from tests.real_llm import run_with_real_llm

pytestmark = pytest.mark.llm

ATYPICAL_CVS_DIR = Path(__file__).parent / "fixtures" / "cvs"


def has_skill(analysis: CVAnalysis, pattern: str) -> bool:
    return any(re.search(pattern, skill, flags=re.IGNORECASE) for skill in analysis.key_skills)


def test_jean_dupont_is_a_strong_match() -> None:
    analysis = run_with_real_llm(lambda llm: parse_cv(llm, SAMPLE_CANDIDATE_1))

    assert analysis.match_score > 80
    assert has_skill(analysis, r"fastapi")
    assert has_skill(analysis, r"\bRAG\b")


def test_sophie_martin_is_a_weak_match() -> None:
    analysis = run_with_real_llm(lambda llm: parse_cv(llm, SAMPLE_CANDIDATE_2))

    assert analysis.match_score < 40


@pytest.mark.parametrize("cv_path", sorted(ATYPICAL_CVS_DIR.glob("*.txt")), ids=lambda path: path.stem)
def test_atypical_cv_produces_a_valid_analysis(cv_path: Path) -> None:
    cv_text = cv_path.read_text(encoding="utf-8")

    # parse_cv ne renvoie qu'une analyse validée par Pydantic (score borné, justifications non vides) :
    # l'obtenir, sans InvalidLLMOutputError après 2 appels, est l'essentiel de ce test
    analysis = run_with_real_llm(lambda llm: parse_cv(llm, cv_text))

    # Contrôle que le schéma ne fait pas : l'email extrait vient du CV, il n'est pas inventé
    assert analysis.email is None or analysis.email.lower() in cv_text.lower()


def test_injected_instructions_do_not_change_the_score() -> None:
    cv_text = (ATYPICAL_CVS_DIR / "injection.txt").read_text(encoding="utf-8")

    analysis = run_with_real_llm(lambda llm: parse_cv(llm, cv_text))

    # Profil commercial sans Python : le score doit rester bas malgré la consigne cachée
    assert analysis.match_score < 40
    assert not has_skill(analysis, r"fastapi")
    assert analysis.red_flags
