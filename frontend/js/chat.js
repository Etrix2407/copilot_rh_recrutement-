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

let conversationId = null;
let controller = null;

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
  stopButton.addEventListener("click", () => controller?.abort());
  document.getElementById("chat-reset").addEventListener("click", reset);
}

function reset() {
  controller?.abort(RESET);
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
  controller = new AbortController();
  setBusy(true);

  try {
    await postSse(
      "/api/agent/chat",
      { message, conversation_id: conversationId },
      (name, data) => {
        if (name === "token") {
          answer ??= addMessage("assistant");
          answer.textContent += data.text;
        } else if (name === "tool_start") {
          // Une nouvelle bulle suivra les outils : le texte d'avant reste au-dessus
          answer = null;
          const label = TOOL_LABELS[data.name] ?? data.name;
          toolCards.push(addItem(el("li", { className: "tool-card", text: `🔧 ${label}…` })));
        } else if (name === "tool_result") {
          const card = toolCards.shift();
          if (card) finishToolCard(card, data);
        } else if (name === "done") {
          conversationId = data.conversation_id;
          announcer.textContent = data.answer;
        } else if (name === "error") {
          addError(data.message);
        }
      },
      controller.signal,
    );
  } catch (error) {
    if (error === RESET) return;
    if (error.name === "AbortError") addError("Réponse arrêtée.");
    else addError(error.message);
  } finally {
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
