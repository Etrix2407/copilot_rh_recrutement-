import pytest
from fastapi.testclient import TestClient

SLOTS_URL = "/api/interviews/slots"


@pytest.fixture
def candidate_id(client: TestClient) -> str:
    return client.app_state["candidate_store"].add(name="Jean Dupont", email="jean.dupont@email.com").id


def test_returns_free_slots_for_existing_candidate(client: TestClient, candidate_id: str) -> None:
    response = client.get(SLOTS_URL, params={"candidate_id": candidate_id, "date": "2026-10-15"})

    assert response.status_code == 200
    assert response.json() == {"date": "2026-10-15", "slots": ["09:00", "11:00", "14:30", "16:00"]}


def test_returns_empty_list_for_date_without_slots(client: TestClient, candidate_id: str) -> None:
    response = client.get(SLOTS_URL, params={"candidate_id": candidate_id, "date": "2026-12-25"})

    assert response.status_code == 200
    assert response.json()["slots"] == []


def test_unknown_candidate_returns_404(client: TestClient) -> None:
    response = client.get(SLOTS_URL, params={"candidate_id": "inconnu", "date": "2026-10-15"})

    assert response.status_code == 404


@pytest.mark.parametrize("date", ["15/10/2026", "2026-13-01", "demain"])
def test_malformed_date_returns_422(client: TestClient, candidate_id: str, date: str) -> None:
    response = client.get(SLOTS_URL, params={"candidate_id": candidate_id, "date": date})

    assert response.status_code == 422
