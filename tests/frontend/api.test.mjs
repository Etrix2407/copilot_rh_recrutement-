// Tests des messages d'erreur de frontend/js/api.js (hors flux SSE, voir sse.test.mjs).

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ApiError, GENERIC_ERROR, NETWORK_ERROR, UNREADABLE_RESPONSE, getJson, postJson, retryDelay,
} from "../../frontend/js/api.js";

const reply = (response) => {
  globalThis.fetch = async () => response;
};

test("réponse 2xx au JSON illisible : ApiError française, pas une SyntaxError", async () => {
  reply(new Response("<html>proxy</html>", { status: 200 }));
  await assert.rejects(getJson("/x"), (error) => error instanceof ApiError && error.message === UNREADABLE_RESPONSE);
  reply(new Response("", { status: 200 }));
  await assert.rejects(postJson("/x", {}), (error) => error instanceof ApiError && error.message === UNREADABLE_RESPONSE);
});

test("erreur sans détail lisible : message sans code technique", async () => {
  reply(new Response("Internal Server Error", { status: 500 }));
  await assert.rejects(getJson("/x"), (error) => error.message === GENERIC_ERROR && error.status === 500);
  assert.doesNotMatch(GENERIC_ERROR, /\d/);
});

test("serveur injoignable : message simple, sans jargon", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("Failed to fetch");
  };
  await assert.rejects(getJson("/x"), (error) => error.message === NETWORK_ERROR && error.status === 0);
  assert.equal(NETWORK_ERROR, "Le serveur ne répond pas. Réessayez dans quelques instants.");
});

test("429 : délai Retry-After transmis, 10 s par défaut", async () => {
  reply(Response.json({ detail: "Trop de demandes." }, { status: 429, headers: { "Retry-After": "7" } }));
  const error = await getJson("/x").catch((caught) => caught);
  assert.equal(error.message, "Trop de demandes.");
  assert.equal(retryDelay(error), 7);
  assert.equal(retryDelay(new ApiError("Trop de demandes.", 429)), 10);
  assert.equal(retryDelay(new ApiError("Erreur.", 500)), 0);
});
