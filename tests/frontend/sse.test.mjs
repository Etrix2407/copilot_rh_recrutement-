// Tests du lecteur de flux SSE de frontend/js/api.js (postSse).

import assert from "node:assert/strict";
import { test } from "node:test";

import { ApiError, NETWORK_ERROR, UNREADABLE_RESPONSE, postSse } from "../../frontend/js/api.js";

const encoder = new TextEncoder();

// Flux de référence : pings, accents et emoji (plusieurs octets), données sur deux lignes
const STREAM = [
  ": ping",
  "",
  "event: start",
  'data: {"conversation_id":"c1"}',
  "",
  ": ping",
  "",
  "event: token",
  'data: {"text":"Réservé 🔧 été"}',
  "",
  "event: token",
  'data: {"text":',
  'data: "multi"}',
  "",
  "event: done",
  'data: {"answer":"fin é"}',
  "",
  "",
].join("\n");

const EXPECTED = [
  ["start", { conversation_id: "c1" }],
  ["token", { text: "Réservé 🔧 été" }],
  ["token", { text: "multi" }],
  ["done", { answer: "fin é" }],
];

// Fait répondre fetch avec ces morceaux d'octets ; renvoie l'état du flux (annulé ou non)
function serve(chunks) {
  const state = { cancelled: false };
  globalThis.fetch = async () => new Response(new ReadableStream({
    pull(controller) {
      if (chunks.length) controller.enqueue(chunks.shift());
      else controller.close();
    },
    cancel() {
      state.cancelled = true;
    },
  }));
  return state;
}

async function collect(chunks) {
  serve(chunks);
  const events = [];
  await postSse("/x", {}, (name, data) => events.push([name, data]));
  return events;
}

// Toutes les découpes en deux morceaux, à chaque octet
async function assertEverySplit(text) {
  const bytes = encoder.encode(text);
  for (let i = 1; i < bytes.length; i++) {
    assert.deepEqual(await collect([bytes.slice(0, i), bytes.slice(i)]), EXPECTED, `coupure à l'octet ${i}`);
  }
}

test("pings ignorés et données sur plusieurs lignes réunies", async () => {
  assert.deepEqual(await collect([encoder.encode(STREAM)]), EXPECTED);
});

test("coupure du flux à n'importe quel octet", async () => {
  await assertEverySplit(STREAM);
});

test("octet par octet", async () => {
  const bytes = [...encoder.encode(STREAM)].map((byte) => new Uint8Array([byte]));
  assert.deepEqual(await collect(bytes), EXPECTED);
});

test("fins de ligne \\r\\n, y compris coupées entre \\r et \\n", async () => {
  const crlf = STREAM.replaceAll("\n", "\r\n");
  assert.deepEqual(await collect([encoder.encode(crlf)]), EXPECTED);
  await assertEverySplit(crlf);
});

test("JSON invalide : lecture annulée et erreur en français", async () => {
  const state = serve([
    encoder.encode('event: token\ndata: {"text":"a"}\n\nevent: token\ndata: {pas du json}\n\n'),
    encoder.encode('event: done\ndata: {"answer":"b"}\n\n'),
  ]);
  const events = [];
  await assert.rejects(
    postSse("/x", {}, (name, data) => events.push([name, data])),
    (error) => error instanceof ApiError && error.message === UNREADABLE_RESPONSE,
  );
  assert.deepEqual(events, [["token", { text: "a" }]]);
  assert.equal(state.cancelled, true);
});

test("coupure réseau en cours de lecture : ApiError avec le message français", async () => {
  let source;
  globalThis.fetch = async () => new Response(new ReadableStream({ start(controller) { source = controller; } }));
  const events = [];
  const reading = postSse("/x", {}, (name, data) => events.push([name, data]));
  await new Promise((resolve) => setTimeout(resolve, 5));
  source.enqueue(encoder.encode('event: start\ndata: {"conversation_id":"c1"}\n\n'));
  await new Promise((resolve) => setTimeout(resolve, 5));
  source.error(new TypeError("network error"));
  await assert.rejects(reading, (error) => error instanceof ApiError && error.message === NETWORK_ERROR && error.status === 0);
  assert.deepEqual(events, [["start", { conversation_id: "c1" }]]);
});

test("arrêt demandé : l'erreur d'arrêt est transmise telle quelle", async () => {
  const controller = new AbortController();
  globalThis.fetch = async (url, options) => new Response(new ReadableStream({
    start(source) {
      options.signal.addEventListener("abort", () => source.error(options.signal.reason));
    },
  }));
  const reading = postSse("/x", {}, () => {}, controller.signal);
  await new Promise((resolve) => setTimeout(resolve, 5));
  controller.abort();
  await assert.rejects(reading, { name: "AbortError" });
});
