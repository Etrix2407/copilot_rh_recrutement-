import asyncio
import base64
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TypeVar

import httpx
import pytest
from pydantic import BaseModel

from app.llm import gemini
from app.llm.base import LLMError, Message, Role, ToolCall, ToolDefinition, ToolResult
from app.llm.gemini import GeminiClient

ResultT = TypeVar("ResultT")

GEMINI_OK_RESPONSE = {"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}}]}
GEMINI_OVERLOADED_RESPONSE = {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}}


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mêmes règles de relance, sans attendre plusieurs secondes entre deux essais
    fast = gemini.TRANSIENT_ERROR_RETRY.model_copy(update={"initial_delay": 0.01, "max_delay": 0.01, "jitter": 0.0})
    monkeypatch.setattr(gemini, "TRANSIENT_ERROR_RETRY", fast)


def run_with_client(
    transport: httpx.AsyncBaseTransport | None, call: Callable[[GeminiClient], Awaitable[ResultT]]
) -> ResultT:
    """Crée un client (transport factice, ou transport httpx par défaut si None), exécute l'appel puis le ferme."""

    async def run() -> ResultT:
        client = GeminiClient(api_key="fake-key", model="test-model", transport=transport)
        try:
            return await call(client)
        finally:
            await client.aclose()

    return asyncio.run(run())


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

    assert run_with_client(transport, lambda client: client.generate("Bonjour")) == "ok"
    assert len(requests) == 3


def test_persistent_overload_becomes_llm_error() -> None:
    transport, requests = gemini_server([503, 503, 503])

    with pytest.raises(LLMError, match="503"):
        run_with_client(transport, lambda client: client.generate("Bonjour"))
    assert len(requests) == gemini.TRANSIENT_ERROR_RETRY.attempts


def test_client_error_is_not_retried() -> None:
    transport, requests = gemini_server([400])

    with pytest.raises(LLMError):
        run_with_client(transport, lambda client: client.generate("Bonjour"))
    assert len(requests) == 1


def test_network_error_becomes_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unreachable(self: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("All connection attempts failed")

    # Coupure simulée dans le transport httpx par défaut : aucun appel réel à Gemini.
    # Le client est créé sans transport, comme dans l'application : si le SDK passait
    # par aiohttp, il ignorerait ce transport et le test échouerait.
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", unreachable)

    with pytest.raises(LLMError, match="injoignable"):
        run_with_client(None, lambda client: client.generate("Bonjour"))


def streaming_server(chunks: list[dict[str, object]]) -> tuple[httpx.MockTransport, list[dict[str, object]]]:
    """Simule le streaming de Gemini : renvoie les morceaux en SSE et garde le corps JSON des requêtes."""
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        stream = "".join(f"data: {json.dumps(chunk)}\r\n\r\n" for chunk in chunks)
        return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"})

    return httpx.MockTransport(handler), bodies


def text_chunk(text: str) -> dict[str, object]:
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}]}


SEARCH_TOOL = ToolDefinition(
    name="search_interview_slots",
    description="Cherche les créneaux.",
    parameters={"type": "object", "properties": {"date": {"type": "string"}}, "required": ["date"]},
)
SIGNATURE = b"opaque-signature"
FUNCTION_CALL_CHUNK = {
    "candidates": [
        {
            "content": {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {
                            "id": "call-1",
                            "name": "search_interview_slots",
                            "args": {"date": "2026-10-15"},
                        },
                        "thoughtSignature": base64.b64encode(SIGNATURE).decode(),
                    }
                ],
            }
        }
    ]
}


def stream_with_tools(transport: httpx.AsyncBaseTransport, messages: list[Message]) -> list[str | Message]:
    async def collect(client: GeminiClient) -> list[str | Message]:
        stream = client.stream_with_tools(messages, system="Agent", tools=[SEARCH_TOOL], temperature=0.0)
        return [item async for item in stream]

    return run_with_client(transport, collect)


def test_text_is_streamed_then_full_message() -> None:
    transport, _ = streaming_server([text_chunk("Bonjour, "), text_chunk("voici les créneaux.")])

    items = stream_with_tools(transport, [Message(role=Role.USER, content="Créneaux ?")])

    assert items == [
        "Bonjour, ",
        "voici les créneaux.",
        Message(role=Role.ASSISTANT, content="Bonjour, voici les créneaux."),
    ]


def test_function_call_becomes_tool_call_with_its_signature() -> None:
    transport, bodies = streaming_server([FUNCTION_CALL_CHUNK])

    items = stream_with_tools(transport, [Message(role=Role.USER, content="Créneaux du 15 ?")])

    assert items == [
        Message(
            role=Role.ASSISTANT,
            tool_calls=[
                ToolCall(
                    id="call-1", name="search_interview_slots", arguments={"date": "2026-10-15"}, signature=SIGNATURE
                )
            ],
        )
    ]
    declaration = bodies[0]["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "search_interview_slots"
    assert declaration["parameters_json_schema"] == SEARCH_TOOL.parameters


def test_history_sends_back_signature_and_tool_result() -> None:
    transport, bodies = streaming_server([text_chunk("ok")])
    call = ToolCall(id="call-1", name="search_interview_slots", arguments={"date": "2026-10-15"}, signature=SIGNATURE)
    history = [
        Message(role=Role.USER, content="Créneaux du 15 ?"),
        Message(role=Role.ASSISTANT, tool_calls=[call]),
        Message(
            role=Role.TOOL,
            tool_results=[ToolResult(call_id="call-1", name="search_interview_slots", content=["09:00"])],
        ),
    ]

    stream_with_tools(transport, history)

    contents = bodies[0]["contents"]
    assert [content["role"] for content in contents] == ["user", "model", "user"]
    assert contents[1]["parts"][0]["thoughtSignature"] == base64.b64encode(SIGNATURE).decode()
    assert contents[2]["parts"][0]["functionResponse"] == {
        "id": "call-1",
        "name": "search_interview_slots",
        # Gemini attend un objet : la liste est enveloppée
        "response": {"result": ["09:00"]},
    }


def test_empty_stream_becomes_llm_error() -> None:
    transport, _ = streaming_server([{"candidates": [{"content": {"role": "model", "parts": []}}]}])

    with pytest.raises(LLMError, match="vide"):
        stream_with_tools(transport, [Message(role=Role.USER, content="Bonjour")])


def test_stream_server_error_becomes_llm_error() -> None:
    transport, _ = gemini_server([400])

    with pytest.raises(LLMError):
        stream_with_tools(transport, [Message(role=Role.USER, content="Bonjour")])


class Answer(BaseModel):
    value: int


def test_generate_json_sends_system_temperature_and_schema() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=text_chunk('{"value": 1}'))

    answer = run_with_client(
        httpx.MockTransport(handler),
        lambda client: client.generate_json(
            [Message(role=Role.USER, content="Question")], system="Consignes", schema=Answer, temperature=0.0
        ),
    )

    assert answer == '{"value": 1}'
    [body] = bodies
    assert body["systemInstruction"]["parts"] == [{"text": "Consignes"}]
    assert body["contents"] == [{"role": "user", "parts": [{"text": "Question"}]}]
    assert body["generationConfig"] == {
        "temperature": 0.0,
        "responseMimeType": "application/json",
        "responseJsonSchema": Answer.model_json_schema(),
    }


def test_thought_parts_are_not_streamed() -> None:
    thought_part = {"text": "Je réfléchis…", "thought": True}
    thought_chunk = {"candidates": [{"content": {"role": "model", "parts": [thought_part]}}]}
    transport, _ = streaming_server([thought_chunk, text_chunk("Voici les créneaux.")])

    items = stream_with_tools(transport, [Message(role=Role.USER, content="Créneaux ?")])

    assert items == ["Voici les créneaux.", Message(role=Role.ASSISTANT, content="Voici les créneaux.")]


class BrokenStream(httpx.AsyncByteStream):
    """Flux SSE coupé après un premier morceau, comme une connexion perdue en cours de réponse."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield f"data: {json.dumps(text_chunk('Bonjour, '))}\r\n\r\n".encode()
        raise httpx.ReadError("connexion interrompue")


def test_network_error_during_stream_becomes_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=BrokenStream(), headers={"content-type": "text/event-stream"})

    with pytest.raises(LLMError, match="injoignable"):
        stream_with_tools(httpx.MockTransport(handler), [Message(role=Role.USER, content="Bonjour")])


# --- Délai maximal des appels ---


class SlowServer(httpx.AsyncBaseTransport):
    """Serveur qui ne répond jamais à temps.

    Applique le délai de lecture de la requête comme le ferait le vrai transport httpx
    (httpx.MockTransport l'ignore) et note les délais reçus.
    """

    def __init__(self) -> None:
        self.read_timeouts: list[float | None] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        read_timeout = request.extensions["timeout"]["read"]
        self.read_timeouts.append(read_timeout)
        try:
            await asyncio.wait_for(asyncio.sleep(5), timeout=read_timeout)
        except TimeoutError:
            raise httpx.ReadTimeout("délai dépassé", request=request) from None
        return httpx.Response(200, json=GEMINI_OK_RESPONSE)


LLM_CALLS: dict[str, Callable[[GeminiClient], Awaitable[object]]] = {
    "generate": lambda client: client.generate("Bonjour"),
    "generate_json": lambda client: client.generate_json(
        [Message(role=Role.USER, content="Bonjour")], system="Analyse", schema=Answer, temperature=0.0
    ),
    "stream_with_tools": lambda client: _collect_stream(client),
}


async def _collect_stream(client: GeminiClient) -> list[str | Message]:
    stream = client.stream_with_tools(
        [Message(role=Role.USER, content="Bonjour")], system="Agent", tools=[SEARCH_TOOL], temperature=0.0
    )
    return [item async for item in stream]


@pytest.mark.parametrize("call", LLM_CALLS.values(), ids=LLM_CALLS.keys())
def test_calls_have_a_timeout_in_seconds(call: Callable[[GeminiClient], Awaitable[object]]) -> None:
    timeouts: list[dict[str, float | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"])
        if "stream" in request.url.path.casefold():
            return httpx.Response(200, text=f"data: {json.dumps(text_chunk('ok'))}\r\n\r\n")
        return httpx.Response(200, json=text_chunk("ok"))

    run_with_client(httpx.MockTransport(handler), call)

    # Le SDK reçoit des millisecondes et transmet des secondes à httpx
    assert timeouts[0]["read"] == gemini.LLM_TIMEOUT_SECONDS


@pytest.mark.parametrize("call", LLM_CALLS.values(), ids=LLM_CALLS.keys())
def test_silent_server_becomes_llm_error(
    monkeypatch: pytest.MonkeyPatch, call: Callable[[GeminiClient], Awaitable[object]]
) -> None:
    monkeypatch.setattr(gemini, "LLM_TIMEOUT_SECONDS", 0.05)
    server = SlowServer()

    with pytest.raises(LLMError, match="injoignable"):
        run_with_client(server, call)
    # Chaque essai (relances du SDK comprises) est borné par le délai
    assert server.read_timeouts == [0.05] * gemini.TRANSIENT_ERROR_RETRY.attempts
