"""Garantit que les données de app/data/ sont identiques à celles du cahier des charges."""

import re
from pathlib import Path

import pytest

from app.data.agenda import RECRUITER_AGENDA
from app.data.candidates import SAMPLE_CANDIDATE_1, SAMPLE_CANDIDATE_2
from app.data.hr_policies import HR_POLICIES
from app.data.job_offers import PYTHON_DEV_JOB_OFFER

SPEC_PATH = Path(__file__).parent.parent / "docs" / "cahier_des_charges.md"


@pytest.fixture(scope="module")
def spec_namespace() -> dict[str, object]:
    """Exécute les blocs Python du cahier des charges et renvoie les noms qu'ils définissent."""
    spec = SPEC_PATH.read_text(encoding="utf-8")
    namespace: dict[str, object] = {}
    for block in re.findall(r"```python\n(.*?)```", spec, flags=re.DOTALL):
        exec(block, namespace)
    return namespace


@pytest.mark.parametrize(
    ("spec_name", "project_value"),
    [
        ("POLITIQUES_RH", HR_POLICIES),
        ("OFFRE_POSTE_DEV_PYTHON", PYTHON_DEV_JOB_OFFER),
        ("CANDIDAT_EXEMPLE_1", SAMPLE_CANDIDATE_1),
        ("CANDIDAT_EXEMPLE_2", SAMPLE_CANDIDATE_2),
        ("AGENDA_RECRUTEUR", RECRUITER_AGENDA),
    ],
)
def test_data_matches_spec(spec_namespace: dict[str, object], spec_name: str, project_value: object) -> None:
    assert project_value == spec_namespace[spec_name]
