from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_llm_client
from app.api.rate_limit import WINDOW_SECONDS, RateLimiter
from app.config import Settings
from app.llm.base import Message, Role
from app.main import create_app
from tests.fakes import FakeEmbeddingFunction, FakeLLMClient

CHAT_URL = "/api/agent/chat"


class FakeClock:
    """Horloge factice : le test avance le temps à la main."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


# --- RateLimiter seul, avec horloge factice ---


def test_requests_beyond_the_limit_must_wait(clock: FakeClock) -> None:
    limiter = RateLimiter(2, clock=clock)

    assert limiter.retry_after("ip") == 0
    clock.advance(10)
    assert limiter.retry_after("ip") == 0

    # La plus ancienne requête sort de la fenêtre dans 60 - 10 secondes
    assert limiter.retry_after("ip") == WINDOW_SECONDS - 10


def test_refused_request_is_not_counted(clock: FakeClock) -> None:
    limiter = RateLimiter(1, clock=clock)
    limiter.retry_after("ip")
    limiter.retry_after("ip")  # refusée

    clock.advance(WINDOW_SECONDS)

    assert limiter.retry_after("ip") == 0


def test_window_slides(clock: FakeClock) -> None:
    limiter = RateLimiter(1, clock=clock)
    limiter.retry_after("ip")

    clock.advance(WINDOW_SECONDS)

    assert limiter.retry_after("ip") == 0


def test_clients_are_counted_separately(clock: FakeClock) -> None:
    limiter = RateLimiter(1, clock=clock)
    limiter.retry_after("a")

    assert limiter.retry_after("b") == 0


def test_inactive_clients_are_forgotten(clock: FakeClock) -> None:
    limiter = RateLimiter(5, clock=clock)
    limiter.retry_after("ancien")
    clock.advance(WINDOW_SECONDS + 1)

    limiter.retry_after("nouveau")

    assert limiter.tracked_clients() == 1


# --- Application avec une limite de 1 demande au LLM par minute ---


@pytest.fixture
def limited_client(test_settings: Settings, fake_llm: FakeLLMClient) -> Iterator[TestClient]:
    settings = test_settings.model_copy(update={"llm_requests_per_minute": 1})
    app = create_app(settings, embedding_function=FakeEmbeddingFunction())
    # Faux LLM : aucun appel réseau
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    fake_llm.tool_answers = [Message(role=Role.ASSISTANT, content="Bonjour")] * 2
    with TestClient(app) as client:
        yield client


def test_second_llm_request_returns_429_with_retry_after(limited_client: TestClient) -> None:
    assert limited_client.post(CHAT_URL, json={"message": "Bonjour"}).status_code == 200

    response = limited_client.post(CHAT_URL, json={"message": "Bonjour"})

    assert response.status_code == 429
    assert "Réessayez" in response.json()["detail"]
    assert int(response.headers["retry-after"]) > 0


def test_invalid_requests_do_not_consume_the_limit(limited_client: TestClient) -> None:
    for payload in [{"message": ""}, {"message": "   "}, {}]:
        assert limited_client.post(CHAT_URL, json=payload).status_code == 422

    assert limited_client.post(CHAT_URL, json={"message": "Bonjour"}).status_code == 200


def test_unknown_conversation_does_not_consume_the_limit(limited_client: TestClient) -> None:
    response = limited_client.post(CHAT_URL, json={"message": "Bonjour", "conversation_id": "inconnue"})
    assert response.status_code == 404

    assert limited_client.post(CHAT_URL, json={"message": "Bonjour"}).status_code == 200


def test_routes_without_llm_are_not_limited(limited_client: TestClient) -> None:
    for _ in range(3):
        assert limited_client.get("/api/candidates").status_code == 200
