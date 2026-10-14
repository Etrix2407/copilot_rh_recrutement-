// Tests de frontend/js/candidates.js : réponses dans le désordre, synthèse, analyse détaillée, suppression.

import assert from "node:assert/strict";
import { test } from "node:test";

import { findAll, loadCandidates, waitFor } from "./fake_browser.mjs";

function candidate(id, name, score, status = "analyzed") {
  return {
    id,
    name,
    email: `${id}@exemple.fr`,
    status,
    analysis: score == null ? null : {
      candidate_name: name,
      email: `${id}@exemple.fr`,
      key_skills: ["Python", "FastAPI"],
      years_of_experience: 6,
      education_level: "bac+5",
      match_score: score,
      score_justifications: [`Justification de ${name}`],
      red_flags: [`Vigilance pour ${name}`],
    },
  };
}

const JEAN = candidate("jean", "Jean Dupont", 85);
const SOPHIE = candidate("sophie", "Sophie Martin", 30, "rejected");
const LEA = candidate("lea", "Léa Petit", null, "new");

// Le serveur renvoie toujours cette liste, et accepte les suppressions
async function loadWith(list) {
  const page = await loadCandidates();
  page.net.reply = (request) => (request.method === "DELETE" ? new Response(null, { status: 204 }) : Response.json(list));
  await page.candidates.refreshCandidates();
  return page;
}

const bodyRows = (page) => findAll(page.$["candidates-table"], (node) => node.tagName === "tr" && node.parentNode.tagName === "tbody");

test("réponses dans le désordre : seule la dernière demande s'affiche", async () => {
  const page = await loadCandidates();
  const pending = [];
  page.net.reply = () => new Promise((resolve) => pending.push(resolve));
  const first = page.candidates.refreshCandidates();
  const second = page.candidates.refreshCandidates();
  await waitFor(() => pending.length === 2);

  // La réponse récente arrive d'abord, l'ancienne ensuite : elle ne doit pas l'écraser
  pending[1](Response.json([JEAN, SOPHIE]));
  await second;
  pending[0](Response.json([]));
  await first;
  assert.deepEqual(page.rows().map((row) => row[0]), ["Jean Dupont", "Sophie Martin"]);
  assert.equal(page.$["candidates-status"].textContent, "");
});

test("synthèse : nombre de candidats, statuts en français, score moyen", async () => {
  const page = await loadWith([JEAN, SOPHIE, LEA]);
  const items = page.$["candidates-summary"].children.map((item) => item.textContent);
  assert.deepEqual(items, ["3 candidats", "Nouveau : 1", "CV analysé : 1", "Refusé : 1", "Score moyen : 58 / 100"]);
  assert.equal(page.$["candidates-summary"].hidden, false);
});

test("cellules étiquetées pour l'affichage en cartes sur mobile", async () => {
  const page = await loadWith([JEAN]);
  const [row] = bodyRows(page);
  assert.deepEqual(row.children.map((cell) => cell.getAttribute("data-label")), ["Nom", "Score", "Statut", "Email", "Action"]);
});

test("le nom ouvre l'analyse complète, « Fermer » la referme et rend le focus au nom", async () => {
  const page = await loadWith([JEAN, LEA]);
  const details = page.$["candidate-details"];
  // Sans analyse, le nom n'est pas un bouton
  assert.equal(page.buttons("Léa Petit").length, 0);

  page.buttons("Jean Dupont")[0].click();
  assert.equal(details.hidden, false);
  assert.match(details.textContent, /85 \/ 100/);
  assert.match(details.textContent, /FastAPI/);
  assert.match(details.textContent, /Justification de Jean Dupont/);
  assert.match(details.textContent, /Vigilance pour Jean Dupont/);
  assert.equal(document.activeElement.tagName, "h3");
  assert.equal(document.activeElement.textContent, "Jean Dupont");
  assert.equal(page.buttons("Jean Dupont")[0].getAttribute("aria-expanded"), "true");

  findAll(details, (node) => node.tagName === "button" && node.textContent === "Fermer")[0].click();
  assert.equal(details.hidden, true);
  assert.equal(document.activeElement, page.buttons("Jean Dupont")[0]);
  assert.equal(document.activeElement.getAttribute("aria-expanded"), "false");
});

test("suppression : focus sur le « Supprimer » suivant, puis sur le message d'état", async () => {
  const page = await loadWith([JEAN, SOPHIE]);
  page.buttons("Supprimer")[0].click();
  await waitFor(() => page.rows().length === 1);
  assert.equal(page.$["candidates-status"].textContent, "Dossier de Jean Dupont supprimé.");
  assert.equal(document.activeElement, page.buttons("Supprimer")[0]);
  assert.equal(document.activeElement.getAttribute("aria-label"), "Supprimer Sophie Martin");

  page.buttons("Supprimer")[0].click();
  await waitFor(() => page.rows().length === 0);
  assert.equal(document.activeElement, page.$["candidates-status"]);
});

test("suppression du candidat dont l'analyse est ouverte : le panneau se referme", async () => {
  const page = await loadWith([JEAN, SOPHIE]);
  page.buttons("Jean Dupont")[0].click();
  page.buttons("Supprimer")[0].click();
  await waitFor(() => page.rows().length === 1);
  assert.equal(page.$["candidate-details"].hidden, true);
});

test("429 : « Réessayer » désactivé pendant le délai indiqué", async () => {
  const page = await loadCandidates();
  page.net.reply = () => Response.json({ detail: "Trop de demandes." }, { status: 429, headers: { "Retry-After": "2" } });
  await page.candidates.refreshCandidates();
  const [retry] = findAll(page.$["candidates-status"], (node) => node.tagName === "button");
  assert.equal(retry.disabled, true);
  assert.equal(retry.textContent, "Réessayer (dans 2 s)");
});
