// Page « Planifier un entretien » : chat avec l'agent, affiché mot à mot.

import { postSse } from "./api.js";
import { el } from "./dom.js";
import { TOOL_LABELS } from "./labels.js";

const log = document.getElementById("chat-log");
const empty = document.getElementById("chat-empty");
const announcer = document.getElementById("chat-announcer");
const form = document.getElementById("chat-form");
const input = document.getElementById("chat-input");
const sendButton = document.getElementById("chat-send");
const stopButton = document.getElementById("chat-stop");

// Raison d'arrêt utilisée par « Nouvelle conversation » : rien à afficher dans ce cas
const RESET = "reset";

// Le LLM envoie ses mots par paquets : l'interface les révèle un par un, à ce rythme
const WORD_DELAY_MS = 40;
// Durée minimale pendant laquelle une carte d'outil reste « en cours », pour qu'on la voie travailler
const TOOL_CARD_MIN_MS = 400;

let conversationId = null;
let controller = null;

// File d'affichage : les mises à jour de l'écran sont jouées dans l'ordre, chacune suivie de sa pause
const display = [];
let displaying = null; // promesse de la file en cours de lecture

function show(update, pauseMs = 0) {
  display.push({ update, pauseMs });
  displaying ??= playDisplay();
}

async function playDisplay() {
  while (display.length) {
    const { update, pauseMs } = display.shift();
    update();
    if (pauseMs) await new Promise((resolve) => setTimeout(resolve, pauseMs));
  }
  displaying = null;
}

// Attend que tout ce qui a été reçu soit affiché
async function displayed() {
  while (displaying) await displaying;
}

export function initChat() {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    send();
  });
  // Entrée envoie, Maj + Entrée va à la ligne
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  });
  for (const chip of form.querySelectorAll("[data-message]")) {
    chip.addEventListener("click", () => {
      input.value = chip.dataset.message;
      input.focus();
    });
  }
  stopButton.addEventListener("click", () => {
    controller?.abort();
    // Arrêt immédiat : ce qui n'est pas encore affiché ne le sera pas
    display.length = 0;
  });
  document.getElementById("chat-reset").addEventListener("click", reset);
}

function reset() {
  controller?.abort(RESET);
  display.length = 0;
  conversationId = null;
  log.replaceChildren();
  empty.hidden = false;
  input.focus();
}

function addItem(item) {
  empty.hidden = true;
  log.append(item);
  item.scrollIntoView({ block: "nearest" });
  return item;
}

function addMessage(role, text = "") {
  const body = el("span", { text });
  addItem(el("li", { className: `message ${role}` }, [
    el("span", { className: "who", text: role === "user" ? "Vous" : "Assistant" }),
    body,
  ]));
  return body;
}

async function send() {
  const message = input.value.trim();
  if (!message || controller) return;
  input.value = "";
  addMessage("user", message);

  let answer = null; // bulle de l'assistant, créée au premier mot
  const toolCards = [];
  let finished = false; // vrai dès qu'un événement done ou error est reçu
  controller = new AbortController();
  setBusy(true);

  try {
    await postSse(
      "/api/agent/chat",
      { message, conversation_id: conversationId },
      (name, data) => {
        if (name === "start") {
          // Connu dès le début : la conversation peut continuer même si la réponse est interrompue
          conversationId = data.conversation_id;
        } else if (name === "token") {
          show(() => {
            answer ??= addMessage("assistant");
            answer.textContent += data.text;
            answer.scrollIntoView({ block: "nearest" });
          }, WORD_DELAY_MS);
        } else if (name === "tool_start") {
          show(() => {
            // Une nouvelle bulle suivra les outils : le texte d'avant reste au-dessus
            answer = null;
            const label = TOOL_LABELS[data.name] ?? data.name;
            toolCards.push(addItem(el("li", { className: "tool-card", text: `🔧 ${label}…` })));
          }, TOOL_CARD_MIN_MS);
        } else if (name === "tool_result") {
          show(() => {
            const card = toolCards.shift();
            if (card) finishToolCard(card, data);
          });
        } else if (name === "done") {
          finished = true;
          conversationId = data.conversation_id;
          // Annoncé aux lecteurs d'écran une fois la réponse entièrement affichée
          show(() => {
            announcer.textContent = data.answer;
          });
        } else if (name === "error") {
          finished = true;
          show(() => addError(data.message));
        }
      },
      controller.signal,
    );
    await displayed();
    // Flux fermé sans fin annoncée : coupure réseau ou serveur arrêté
    if (!finished) addError("La réponse a été interrompue. Réessayez.");
  } catch (error) {
    if (error === RESET) return;
    await displayed();
    // Demande refusée avant toute réponse (quota, conversation expirée…) : le texte saisi est rendu
    if (error.status && !input.value) input.value = message;
    if (error.name === "AbortError") addError("Réponse arrêtée.");
    else if (error.status === 404) {
      // Conversation oubliée par le serveur (redémarrage) : la prochaine demande en ouvre une nouvelle
      conversationId = null;
      addError("Cette conversation a expiré. Renvoyez votre demande pour en commencer une nouvelle.");
    } else addError(error.message);
  } finally {
    // Outils lancés dont le résultat n'est jamais arrivé
    for (const card of toolCards) {
      card.className = "tool-card failed";
      card.textContent = `✖ ${card.textContent.replace(/^🔧 |…$/gu, "")} : interrompu`;
    }
    controller = null;
    setBusy(false);
    input.focus();
  }
}

function finishToolCard(card, result) {
  const label = TOOL_LABELS[result.name] ?? result.name;
  card.className = `tool-card ${result.success ? "done" : "failed"}`;
  card.replaceChildren(
    `${result.success ? "✔" : "✖"} ${label}`,
    el("span", { className: "detail", text: result.summary }),
  );
}

function addError(text) {
  const item = addItem(el("li", { className: "message assistant error", text }));
  announcer.textContent = text;
  return item;
}

function setBusy(busy) {
  sendButton.disabled = busy;
  stopButton.hidden = !busy;
}
