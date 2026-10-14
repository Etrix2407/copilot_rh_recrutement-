// Tests de frontend/js/chat.js : file d'affichage, boutons « Arrêter » et « Nouvelle conversation », erreurs.

import assert from "node:assert/strict";
import { test } from "node:test";

import { NETWORK_ERROR } from "../../frontend/js/api.js";
import { loadChat, sleep, sse, waitFor } from "./fake_browser.mjs";

// Pauses très longues : un test qui les attendrait dépasserait le délai de waitFor
const SLOW = { wordMs: 10_000, toolCardMs: 10_000 };

const idle = (page) => waitFor(() => !page.busy(), { message: "le bouton Envoyer n'est pas réactivé" });

// Attend que le premier élément de la réponse (mot ou carte d'outil) remplace la bulle « réfléchit »
const firstShown = (page) => waitFor(
  () => page.items().length === 2 && !page.items()[1].className.includes("thinking"),
  { message: "rien ne s'affiche après la bulle « réfléchit »" },
);

test("une erreur seule, file vide, s'affiche et réactive Envoyer (gel corrigé)", async () => {
  const page = await loadChat();
  page.submit("bonjour");
  const server = page.net.servers[0];
  server.push(sse("start", { conversation_id: "c1" }));
  server.push(sse("error", { message: "Le service IA est indisponible." }));
  server.close();

  await idle(page);
  assert.deepEqual(page.items().at(-1), {
    className: "message assistant error",
    text: "Le service IA est indisponible.",
  });
  assert.equal(page.$["chat-stop"].hidden, true);
  assert.equal(page.$["chat-announcer"].textContent, "Le service IA est indisponible.");
});

test("ordre d'affichage : carte d'outil, résultat, mots, puis annonce", async () => {
  const page = await loadChat({ wordMs: 1, toolCardMs: 50 });
  page.submit("trouve un créneau");
  const server = page.net.servers[0];
  server.push(sse("start", { conversation_id: "c1" }));
  server.push(sse("tool_start", { name: "rechercher_creneaux_entretien" }));
  server.push(sse("tool_result", { name: "rechercher_creneaux_entretien", success: true, summary: "2 créneaux" }));
  server.push(sse("token", { text: "Deux " }));
  server.push(sse("token", { text: "créneaux." }));
  server.push(sse("done", { conversation_id: "c1", answer: "Deux créneaux." }));
  server.close();

  // Pendant la pause de la carte : outil « en cours », pas encore de mots ; seul le début est annoncé
  await firstShown(page);
  assert.deepEqual(page.items()[1], { className: "tool-card", text: "🔧 Recherche de créneaux…" });
  assert.equal(page.$["chat-announcer"].textContent, "Recherche en cours…");

  await idle(page);
  assert.deepEqual(page.items(), [
    { className: "message user", text: "Voustrouve un créneau" },
    { className: "tool-card done", text: "✔ Recherche de créneaux2 créneaux" },
    { className: "message assistant", text: "AssistantDeux créneaux." },
  ]);
  assert.equal(page.$["chat-announcer"].textContent, "Deux créneaux.");
});

test("Arrêter pendant le flux : tout ce qui est reçu s'affiche aussitôt, réservation comprise", async () => {
  const page = await loadChat(SLOW);
  page.submit("réserve");
  const server = page.net.servers[0];
  server.push(sse("start", { conversation_id: "c1" }));
  server.push(sse("token", { text: "Je réserve." }));
  server.push(sse("tool_start", { name: "reserver_entretien" }));
  server.push(sse("tool_result", { name: "reserver_entretien", success: true, summary: "Réservé le 2026-10-15" }));
  server.push(sse("tool_start", { name: "mettre_a_jour_statut_candidat" }));
  // Le premier mot est affiché, le reste attend derrière une pause de 10 s
  await firstShown(page);

  page.$["chat-stop"].click();
  await idle(page);
  assert.deepEqual(page.items(), [
    { className: "message user", text: "Vousréserve" },
    { className: "message assistant", text: "AssistantJe réserve." },
    { className: "tool-card done", text: "✔ Réservation de l'entretienRéservé le 2026-10-15" },
    // Résultat jamais reçu : ni succès ni échec affirmé
    { className: "tool-card level-medium", text: "⚠ Mise à jour du statut : résultat non reçu" },
    { className: "message assistant error", text: "Réponse arrêtée." },
  ]);
  assert.equal(page.$["chat-stop"].hidden, true);
});

for (const closed of [true, false]) {
  test(`Arrêter après done (flux ${closed ? "fermé" : "encore ouvert"}) : la réponse complète s'affiche`, async () => {
    const page = await loadChat(SLOW);
    page.submit("salut");
    const server = page.net.servers[0];
    const words = ["Le ", "créneau ", "est ", "réservé."];
    server.push(sse("start", { conversation_id: "c1" }));
    for (const word of words) server.push(sse("token", { text: word }));
    server.push(sse("done", { conversation_id: "c1", answer: words.join("") }));
    if (closed) server.close();
    await firstShown(page);

    page.$["chat-stop"].click();
    await idle(page);
    // Rien de tronqué, et aucun message d'interruption : la réponse était entièrement reçue
    assert.deepEqual(page.items().slice(1), [
      { className: "message assistant", text: "AssistantLe créneau est réservé." },
    ]);
    assert.equal(page.$["chat-announcer"].textContent, "Le créneau est réservé.");
  });
}

test("conversation expirée (404) : id oublié, message affiché, texte rendu", async () => {
  const page = await loadChat();
  page.submit("premier");
  const server = page.net.servers[0];
  server.push(sse("start", { conversation_id: "c1" }));
  server.push(sse("done", { conversation_id: "c1", answer: "ok" }));
  server.close();
  await idle(page);

  page.net.reply = () => Response.json({ detail: "Conversation introuvable." }, { status: 404 });
  page.submit("suite");
  assert.equal(page.net.requests[1].body.conversation_id, "c1");
  await idle(page);
  assert.equal(page.items().at(-1).className, "message assistant error");
  assert.match(page.items().at(-1).text, /a expiré/);
  assert.equal(page.$["chat-input"].value, "suite");

  page.net.reply = null;
  page.submit("suite");
  assert.equal(page.net.requests[2].body.conversation_id, null);
});

test("double envoi bloqué tant que la réponse n'est pas finie", async () => {
  const page = await loadChat();
  page.submit("un");
  page.submit("deux");
  page.$["chat-input"].dispatch("keydown", { key: "Enter", shiftKey: false });
  assert.equal(page.net.requests.length, 1);
  assert.equal(page.busy(), true);

  page.net.servers[0].push(sse("done", { conversation_id: "c1", answer: "" }));
  page.net.servers[0].close();
  await idle(page);
  page.submit("trois");
  assert.equal(page.net.requests.length, 2);
});

test("coupure réseau en plein flux : message français, pas celui du navigateur", async () => {
  const page = await loadChat();
  page.submit("salut");
  const server = page.net.servers[0];
  server.push(sse("start", { conversation_id: "c1" }));
  server.push(sse("token", { text: "Bon" }));
  await firstShown(page);
  server.fail(new TypeError("network error"));

  await idle(page);
  assert.deepEqual(page.items().at(-1), { className: "message assistant error", text: NETWORK_ERROR });
});

for (const finished of [false, true]) {
  test(`Nouvelle conversation pendant l'affichage (flux ${finished ? "terminé" : "en cours"}) : rien de l'ancienne, envoi immédiat accepté`, async () => {
    const page = await loadChat(SLOW);
    page.submit("ancienne demande");
    const server = page.net.servers[0];
    server.push(sse("start", { conversation_id: "c1" }));
    for (const word of ["un ", "deux ", "trois "]) server.push(sse("token", { text: word }));
    server.push(sse("tool_start", { name: "rechercher_creneaux_entretien" }));
    if (finished) {
      server.push(sse("tool_result", { name: "rechercher_creneaux_entretien", success: true, summary: "ok" }));
      server.push(sse("done", { conversation_id: "c1", answer: "un deux trois" }));
      server.close();
    }
    await firstShown(page);

    page.$["chat-reset"].click();
    assert.deepEqual(page.items(), []);
    assert.equal(page.$["chat-empty"].hidden, false);
    assert.equal(page.busy(), false);

    // Envoi dans la foulée : accepté, dans une nouvelle conversation
    page.chat.timing.wordMs = 1;
    page.chat.timing.toolCardMs = 1;
    page.submit("nouvelle demande");
    assert.equal(page.net.requests.length, 2);
    assert.equal(page.net.requests[1].body.conversation_id, null);

    const next = page.net.servers[1];
    next.push(sse("start", { conversation_id: "c2" }));
    next.push(sse("token", { text: "Réponse2" }));
    next.push(sse("done", { conversation_id: "c2", answer: "Réponse2" }));
    next.close();
    await idle(page);
    await sleep(30);
    assert.deepEqual(page.items(), [
      { className: "message user", text: "Vousnouvelle demande" },
      { className: "message assistant", text: "AssistantRéponse2" },
    ]);
  });
}

test("bulle « L'assistant réfléchit… » dès l'envoi, retirée au premier mot", async () => {
  const page = await loadChat();
  page.submit("bonjour");
  assert.deepEqual(page.items(), [
    { className: "message user", text: "Vousbonjour" },
    { className: "message assistant thinking", text: "AssistantL'assistant réfléchit…" },
  ]);
  assert.equal(page.$["chat-announcer"].textContent, "Recherche en cours…");

  const server = page.net.servers[0];
  server.push(sse("token", { text: "Salut" }));
  server.push(sse("done", { conversation_id: "c1", answer: "Salut" }));
  server.close();
  await idle(page);
  assert.deepEqual(page.items().map((item) => item.className), ["message user", "message assistant"]);
});

test("bulle « réfléchit » retirée à la première carte d'outil, et en fin de réponse vide", async () => {
  const page = await loadChat(SLOW);
  page.submit("créneau ?");
  const server = page.net.servers[0];
  server.push(sse("tool_start", { name: "rechercher_creneaux_entretien" }));
  await firstShown(page);
  assert.equal(page.items()[1].className, "tool-card");
  // Arrêt : la pause de 10 s en cours est interrompue (sinon le test attendrait sa fin)
  page.$["chat-stop"].click();
  await idle(page);

  const empty = await loadChat();
  empty.submit("rien");
  empty.net.servers[0].push(sse("done", { conversation_id: "c1", answer: "" }));
  empty.net.servers[0].close();
  await idle(empty);
  assert.deepEqual(empty.items().map((item) => item.className), ["message user"]);
});

test("chaque résultat d'outil est annoncé ; outil inconnu : libellé générique", async () => {
  const page = await loadChat({ wordMs: 1, toolCardMs: 1 });
  page.submit("réserve");
  const server = page.net.servers[0];
  server.push(sse("tool_start", { name: "reserver_entretien" }));
  server.push(sse("tool_result", { name: "reserver_entretien", success: true, summary: "Entretien réservé." }));
  await waitFor(() => page.$["chat-announcer"].textContent === "Réservation de l'entretien : réussie");

  server.push(sse("tool_start", { name: "outil_futur" }));
  server.push(sse("tool_result", { name: "outil_futur", success: false, summary: "Impossible." }));
  await waitFor(() => page.$["chat-announcer"].textContent === "Action de l'assistant : échouée");
  assert.deepEqual(page.items().at(-1), { className: "tool-card failed", text: "✖ Action de l'assistantImpossible." });

  server.push(sse("done", { conversation_id: "c1", answer: "Fini." }));
  server.close();
  await idle(page);
  assert.equal(page.$["chat-announcer"].textContent, "Fini.");
});

test("emojis des cartes d'outil masqués aux lecteurs d'écran", async () => {
  const page = await loadChat();
  page.submit("réserve");
  const server = page.net.servers[0];
  server.push(sse("tool_start", { name: "reserver_entretien" }));
  server.push(sse("tool_result", { name: "reserver_entretien", success: true, summary: "ok" }));
  server.push(sse("done", { conversation_id: "c1", answer: "" }));
  server.close();
  await idle(page);
  const [emoji] = page.$["chat-log"].children[1].children;
  assert.equal(emoji.textContent, "✔");
  assert.equal(emoji.getAttribute("aria-hidden"), "true");
});

test("Entrée pendant une composition (IME) n'envoie pas ; Entrée ensuite envoie", async () => {
  const page = await loadChat();
  page.$["chat-input"].value = "こんにちは";
  page.$["chat-input"].dispatch("keydown", { key: "Enter", shiftKey: false, isComposing: true });
  assert.equal(page.net.requests.length, 0);
  page.$["chat-input"].dispatch("keydown", { key: "Enter", shiftKey: false, isComposing: false });
  assert.equal(page.net.requests.length, 1);
});

test("coupure réseau après done : aucun message d'erreur parasite", async () => {
  const page = await loadChat();
  page.submit("salut");
  const server = page.net.servers[0];
  server.push(sse("token", { text: "Bonjour." }));
  server.push(sse("done", { conversation_id: "c1", answer: "Bonjour." }));
  await waitFor(() => page.items().some((item) => item.className === "message assistant"));
  server.fail(new TypeError("network error"));
  await idle(page);
  assert.deepEqual(page.items().map((item) => item.className), ["message user", "message assistant"]);
});

test("refus 409 du serveur : le message reçu est affiché tel quel, texte rendu", async () => {
  const page = await loadChat();
  page.net.reply = () => Response.json({ detail: "Une réponse est déjà en cours." }, { status: 409 });
  page.submit("encore");
  await idle(page);
  assert.deepEqual(page.items().at(-1), { className: "message assistant error", text: "Une réponse est déjà en cours." });
  assert.equal(page.$["chat-input"].value, "encore");
});
