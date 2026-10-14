import json

from fastapi.testclient import TestClient

from app.api.errors import LLM_UNAVAILABLE

from app.data.hr_policies import HR_POLICIES
from app.llm.base import LLMError
from app.services.hr_assistant import REFUSAL
from tests.fakes import FakeLLMClient

ASK_URL = "/api/rag/ask"


def test_ask_returns_answer_and_sources(client: TestClient, fake_llm: FakeLLMClient) -> None:
    fake_llm.json_answers = [
        json.dumps({"answered": True, "answer": "10 RTT par an.", "source_ids": ["rh_doc_02"]})
    ]

    response = client.post(ASK_URL, json={"question": "Combien de RTT et puis-je les placer sur un CET ?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "10 RTT par an."
    rtt_policy = HR_POLICIES[1]
    assert body["sources"] == [{"id": rtt_policy["id"], "title": rtt_policy["titre"], "text": rtt_policy["texte"]}]


def test_refusal_has_no_sources(client: TestClient, fake_llm: FakeLLMClient) -> None:
    fake_llm.json_answers = [json.dumps({"answered": False, "answer": "", "source_ids": []})]

    response = client.post(ASK_URL, json={"question": "Quelle est la prime de naissance ?"})

    assert response.json() == {"answer": REFUSAL, "sources": []}


def test_blank_question_is_rejected(client: TestClient) -> None:
    assert client.post(ASK_URL, json={"question": "   "}).status_code == 422


def test_llm_failure_returns_502(client: TestClient, fake_llm: FakeLLMClient) -> None:
    fake_llm.json_answers = [LLMError("quota dépassé")]

    response = client.post(ASK_URL, json={"question": "Combien de RTT ?"})

    assert response.status_code == 502
    # Le détail interne de l'erreur reste dans les logs
    assert response.json() == {"detail": LLM_UNAVAILABLE}


def test_invalid_llm_answers_return_502(client: TestClient, fake_llm: FakeLLMClient) -> None:
    # Réponse invalide puis relance invalide : InvalidLLMOutputError après 2 appels
    fake_llm.json_answers = ["pas du JSON", "{}"]

    response = client.post(ASK_URL, json={"question": "Combien de RTT ?"})

    assert response.status_code == 502
    assert response.json() == {"detail": LLM_UNAVAILABLE}
    assert len(fake_llm.json_calls) == 2
