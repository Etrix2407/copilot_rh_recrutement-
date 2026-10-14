"""Les 3 tests officiels joués de bout en bout, à travers l'API, avec le vrai LLM.

Ils passent par les mêmes routes que l'interface (analyse, assistant RH, chat SSE).
Ces tests consomment du quota : ils ne tournent qu'avec `pytest -m llm`.
"""

import datetime
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.data.agenda import RECRUITER_AGENDA
from app.data.candidates import SAMPLE_CANDIDATE_1, SAMPLE_CANDIDATE_2
from app.main import create_app
from app.services.hr_assistant import REFUSAL
from tests.fakes import INITIAL_SLOTS_2026_10_15, parse_sse

pytestmark = pytest.mark.llm

OFFICIAL_DATE = "2026-10-15"


@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    """Application réelle (LLM et embedding du .env), avec ses propres bases temporaires."""
    path: Path = tmp_path_factory.mktemp("api")
    settings = get_settings().model_copy(
        update={
            "chroma_path": str(path / "chroma"),
            "database_path": str(path / "candidates.db"),
            "allowed_hosts": ["testserver"],
            # « Date du jour » fixée la veille : le 15/10/2026 reste une date future quel que soit le jour réel
            "demo_date": datetime.date(2026, 10, 14),
        }
    )
    with TestClient(create_app(settings)) as client:
        yield client


def analyze(api: TestClient, cv_text: str) -> dict[str, object]:
    response = api.post("/api/candidates/parse", data={"text": cv_text})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="module")
def jean_dupont(api: TestClient) -> dict[str, object]:
    """Jean Dupont analysé une seule fois par l'API, partagé par les tests 1 et 3.

    Le test 3 en dépend explicitement : il reste valable quel que soit l'ordre d'exécution.
    """
    return analyze(api, SAMPLE_CANDIDATE_1)


def test_official_1_parsing_through_the_api(api: TestClient, jean_dupont: dict[str, object]) -> None:
    sophie_martin = analyze(api, SAMPLE_CANDIDATE_2)

    analysis = jean_dupont["analysis"]
    assert analysis["match_score"] > 80
    skills = " ".join(analysis["key_skills"])
    assert re.search(r"fastapi", skills, re.IGNORECASE)
    assert re.search(r"\bRAG\b", skills)
    assert sophie_martin["analysis"]["match_score"] < 40


def test_official_2_rag_through_the_api(api: TestClient) -> None:
    answered_response = api.post(
        "/api/rag/ask", json={"question": "Combien de jours de RTT ai-je droit et puis-je les placer sur un CET ?"}
    )
    birth_bonus = "Quelle est la prime de naissance accordée par l'entreprise ?"
    refused = api.post("/api/rag/ask", json={"question": birth_bonus})

    # Code vérifié d'abord : un 502 (quota du LLM dépassé) doit se lire comme tel, pas comme un KeyError
    assert answered_response.status_code == 200, answered_response.text
    assert refused.status_code == 200, refused.text
    answered = answered_response.json()

    assert "rh_doc_02" in [source["id"] for source in answered["sources"]]
    # Les deux chiffres de la politique : 10 RTT par an, dont 5 plaçables sur le CET
    assert re.search(r"\b10\b", answered["answer"])
    assert re.search(r"\b5\b", answered["answer"])
    assert refused.json() == {"answer": REFUSAL, "sources": []}


def test_official_3_agent_through_the_sse_chat(api: TestClient, jean_dupont: dict[str, object]) -> None:
    assert RECRUITER_AGENDA[OFFICIAL_DATE] == INITIAL_SLOTS_2026_10_15
    message = (
        f"Trouve-moi un créneau le {OFFICIAL_DATE} pour réserver un entretien avec Jean Dupont (jean.dupont@email.com)"
    )

    response = api.post("/api/agent/chat", json={"message": message})

    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    tools = [data["name"] for name, data in events if name == "tool_start"]
    assert "rechercher_creneaux_entretien" in tools
    assert "reserver_entretien" in tools
    assert tools.index("rechercher_creneaux_entretien") < tools.index("reserver_entretien"), tools
    bookings = [data for name, data in events if name == "tool_result" and data["name"] == "reserver_entretien"]
    assert any(booking["success"] for booking in bookings)
    # Le créneau réservé a bien été retiré de l'agenda du recruteur
    assert len(RECRUITER_AGENDA[OFFICIAL_DATE]) == 3
    assert [name for name, _ in events if name == "token"], "la réponse doit arriver mot à mot"
    assert events[-1][0] == "done"
    candidates = {candidate["id"]: candidate for candidate in api.get("/api/candidates").json()}
    assert candidates[jean_dupont["id"]]["status"] == "interview_scheduled"
