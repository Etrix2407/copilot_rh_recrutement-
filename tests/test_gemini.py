import asyncio
import base64
import json

import httpx
import pytest

from app.llm import gemini
from app.llm.base import LLMError, Message, Role, ToolCall, ToolDefinition, ToolResult
from app.llm.gemini import GeminiClient

GEMINI_OK_RESPONSE = {"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}}]}
GEMINI_OVERLOADED_RESPONSE = {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}}


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mêmes règles de relance, sans attendre plusieurs secondes entre deux essais
    fast = gemini.TRANSIENT_ERROR_RETRY.model_copy(update={"initial_delay": 0.01, "max_delay": 0.01, "jitter": 0.0})
    monkeypatch.setattr(gemini, "TRANSIENT_ERROR_RETRY", fast)


def gemini_server(statuses: list[int]) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    """Simule Gemini : répond avec les codes HTTP donnés, dans l'ordre."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        status = statuses[len(requests) - 1]
        return httpx.Response(status, json=GEMINI_OK_RESPONSE if status == 200 else GEMINI_OVERLOADED_RESPONSE)

    return httpx.MockTransport(handler), requests


def test_overloaded_model_is_retried() -> None:
    transport, requests = gemini_server([503, 503, 200])
    client = GeminiClient(api_key="fake-key", model="test-model", transport=transport)

    assert asyncio.run(client.generate("Bonjour")) == "ok"
    assert len(requests) == 3


def test_persistent_overload_becomes_llm_error() -> None:
    transport, requests = gemini_server([503, 503, 503])
    client = GeminiClient(api_key="fake-key", model="test-model", transport=transport)

    with pytest.raises(LLMError, match="503"):
        asyncio.run(client.generate("Bonjour"))
    assert len(requests) == gemini.TRANSIENT_ERROR_RETRY.attempts


def test_client_error_is_not_retried() -> None:
    transport, requests = gemini_server([400])
    client = GeminiClient(api_key="fake-key", model="test-model", transport=transport)

    with pytest.raises(LLMError):
        asyncio.run(client.generate("Bonjour"))
    assert len(requests) == 1


def test_network_error_becomes_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unreachable(self: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("All connection attempts failed")

    # Coupure simulée dans le transport httpx par défaut : aucun appel réel à Gemini.
    # Le client est créé sans transport, comme dans l'application : si le SDK passait
    # par aiohttp, il ignorerait ce transport et le test échouerait.
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", unreachable)
    client = GeminiClient(api_key="fake-key", model="test-model")

    with pytest.raises(LLMError, match="injoignable"):
        asyncio.run(client.generate("Bonjour"))


def recording_server(response: dict[str, object]) -> tuple[httpx.MockTransport, list[dict[str, object]]]:
    """Simule Gemini : renvoie toujours la même réponse et garde le corps JSON des requêtes."""
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=response)

    return httpx.MockTransport(handler), bodies


SEARCH_TOOL = ToolDefinition(
    name="search_interview_slots",
    description="Cherche les créneaux.",
    parameters={"type": "object", "properties": {"date": {"type": "string"}}, "required": ["date"]},
)
SIGNATURE = b"opaque-signature"
FUNCTION_CALL_RESPONSE = {
    "candidates": [
        {
            "content": {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {"id": "call-1", "name": "search_interview_slots", "args": {"date": "2026-10-15"}},
                        "thoughtSignature": base64.b64encode(SIGNATURE).decode(),
                    }
                ],
            }
        }
    ]
}


def generate_with_tools(transport: httpx.MockTransport, messages: list[Message]) -> Message:
    client = GeminiClient(api_key="fake-key", model="test-model", transport=transport)
    return asyncio.run(client.generate_with_tools(messages, system="Agent", tools=[SEARCH_TOOL], temperature=0.0))


def test_function_call_becomes_tool_call_with_its_signature() -> None:
    transport, bodies = recording_server(FUNCTION_CALL_RESPONSE)

    reply = generate_with_tools(transport, [Message(role=Role.USER, content="Créneaux du 15 ?")])

    assert reply.role is Role.ASSISTANT
    assert reply.tool_calls == [
        ToolCall(id="call-1", name="search_interview_slots", arguments={"date": "2026-10-15"}, signature=SIGNATURE)
    ]
    declaration = bodies[0]["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "search_interview_slots"
    assert declaration["parameters_json_schema"] == SEARCH_TOOL.parameters


def test_history_sends_back_signature_and_tool_result() -> None:
    transport, bodies = recording_server(GEMINI_OK_RESPONSE)
    call = ToolCall(id="call-1", name="search_interview_slots", arguments={"date": "2026-10-15"}, signature=SIGNATURE)
    history = [
        Message(role=Role.USER, content="Créneaux du 15 ?"),
        Message(role=Role.ASSISTANT, tool_calls=[call]),
        Message(
            role=Role.TOOL,
            tool_results=[ToolResult(call_id="call-1", name="search_interview_slots", content=["09:00"])],
        ),
    ]

    reply = generate_with_tools(transport, history)

    assert reply == Message(role=Role.ASSISTANT, content="ok")
    contents = bodies[0]["contents"]
    assert [content["role"] for content in contents] == ["user", "model", "user"]
    assert contents[1]["parts"][0]["thoughtSignature"] == base64.b64encode(SIGNATURE).decode()
    assert contents[2]["parts"][0]["functionResponse"] == {
        "id": "call-1",
        "name": "search_interview_slots",
        # Gemini attend un objet : la liste est enveloppée
        "response": {"result": ["09:00"]},
    }


def test_empty_tool_reply_becomes_llm_error() -> None:
    transport, _ = recording_server({"candidates": [{"content": {"role": "model", "parts": []}}]})

    with pytest.raises(LLMError, match="vide"):
        generate_with_tools(transport, [Message(role=Role.USER, content="Bonjour")])
