// Page « Planifier un entretien » : chat avec l'agent, affiché mot à mot.

import { postSse } from "./api.js";
import { el, icon } from "./dom.js";
import { toolLabel } from "./labels.js";

const log = document.getElementById("chat-log");
const empty = document.getElementById("chat-empty");
const announcer = document.getElementById("chat-announcer");
const form = document.getElementById("chat-form");
const input = document.getElementById("chat-input");
const sendButton = document.getElementById("chat-send");
const stopButton = document.getElementById("chat-stop");

// Raison d'arrêt utilisée par « Nouvelle conversation » : rien à afficher dans ce cas
const RESET = "reset";

// Rythme d'affichage, en millisecondes (exporté pour que les tests puissent l'accélérer)
export const timing = {
  // Le LLM envoie ses mots par paquets : l'interface les révèle un par un, à ce rythme
  wordMs: 40,
  // Durée minimale pendant laquelle une carte d'outil reste « en cours », pour qu'on la voie travailler
  toolCardMs: 400,
};

let conversationId = null;
let controller = null; // présent tant qu'une demande est en cours
let thinking = null; // bulle « L'assistant réfléchit… », retirée dès que quelque chose s'affiche

// File d'affichage : les mises à jour de l'écran sont jouées dans l'ordre, chacune suivie de sa pause
const display = [];
let displaying = null; // promesse de la file en cours de lecture
let endPause = null; // termine tout de suite la pause en cours

function show(update, pauseMs = 0) {
  display.push({ update, pauseMs });
  // Lecture lancée au tour suivant : appelée directement, une file sans pause se viderait avant
  // l'affectation, et « displaying » garderait une promesse terminée (l'affichage se figerait)
  displaying ??= Promise.resolve().then(playDisplay);
}

async function playDisplay() {
  while (display.length) {
    const { update, pauseMs } = display.shift();
    update();
    if (pauseMs) {
      await new Promise((resolve) => {
        const timer = setTimeout(resolve, pauseMs);
        endPause = () => {
          clearTimeout(timer);
          resolve();
        };
      });
      endPause = null;
    }
  }
  displaying = null;
}

// Affiche aussitôt, sans les pauses, tout ce qui a déjà été reçu (bouton « Arrêter »)
function flushDisplay() {
  endPause?.();
  for (const { update } of display.splice(0)) update();
}

// Oublie tout ce qui n'est pas encore affiché (« Nouvelle conversation »)
function dropDisplay() {
  endPause?.();
  display.length = 0;
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
  // Entrée envoie, Maj + Entrée va à la ligne ; pendant une saisie de caractères composés
  // (accents, japonais… : isComposing), Entrée valide le caractère et n'envoie rien
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
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
    // Seul ce qui n'est pas encore arrivé est perdu : une réservation déjà confirmée reste visible
    flushDisplay();
  });
  document.getElementById("chat-reset").addEventListener("click", reset);
}

function reset() {
  controller?.abort(RESET);
  // La demande abandonnée ne touche plus à l'écran : un nouvel envoi est possible tout de suite
  controller = null;
  setBusy(false);
  dropDisplay();
  conversationId = null;
  thinking = null;
  log.replaceChildren();
  empty.hidden = false;
  input.focus();
}

// Tout nouvel élément du fil remplace la bulle « réfléchit »
function addItem(item) {
  thinking?.remove();
  thinking = null;
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
  // Retour immédiat : on voit que la demande est partie avant le premier mot
  thinking = addItem(el("li", { className: "message assistant thinking" }, [
    el("span", { className: "who", text: "Assistant" }),
    el("span", { className: "loading", text: "L'assistant réfléchit…" }),
  ]));
  announcer.textContent = "Recherche en cours…";

  let answer = null; // bulle de l'assistant, créée au premier mot
  const toolCards = [];
  let finished = false; // vrai dès qu'un événement done ou error est reçu
  const ownController = new AbortController();
  controller = ownController;
  // Faux après « Nouvelle conversation » : cette demande ne doit plus rien afficher
  const isCurrent = () => controller === ownController;
  setBusy(true);

  try {
    await postSse(
      "/api/agent/chat",
      { message, conversation_id: conversationId },
      (name, data) => {
        // Après « Arrêter » ou « Nouvelle conversation », plus rien n'est affiché
        if (!isCurrent() || ownController.signal.aborted) return;
        if (name === "start") {
          // Connu dès le début : la conversation peut continuer même si la réponse est interrompue
          conversationId = data.conversation_id;
        } else if (name === "token") {
          show(() => {
            answer ??= addMessage("assistant");
            answer.textContent += data.text;
            answer.scrollIntoView({ block: "nearest" });
          }, timing.wordMs);
        } else if (name === "tool_start") {
          show(() => {
            // Une nouvelle bulle suivra les outils : le texte d'avant reste au-dessus
            answer = null;
            const label = toolLabel(data.name);
            const card = addItem(el("li", { className: "tool-card" }, [icon("🔧"), ` ${label}…`]));
            card.dataset.label = label;
            toolCards.push(card);
          }, timing.toolCardMs);
        } else if (name === "tool_result") {
          show(() => {
            const card = toolCards.shift();
            if (card) finishToolCard(card, data);
            announcer.textContent = `${toolLabel(data.name)} : ${data.success ? "réussie" : "échouée"}`;
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
      ownController.signal,
    );
    await displayed();
    if (!isCurrent()) return;
    // Flux fermé sans fin annoncée : coupure réseau ou serveur arrêté
    if (!finished) addError("La réponse a été interrompue. Réessayez.");
  } catch (error) {
    if (!isCurrent()) return;
    await displayed();
    // Demande refusée avant toute réponse (quota, conversation expirée…) : le texte saisi est rendu
    if (error.status && !input.value) input.value = message;
    if (finished) {
      // Réponse déjà complète (done ou error reçu) : un arrêt ou une coupure ensuite n'a rien perdu
    } else if (error.name === "AbortError") {
      addError("Réponse arrêtée.");
    } else if (error.status === 404) {
      // Conversation oubliée par le serveur (redémarrage) : la prochaine demande en ouvre une nouvelle
      conversationId = null;
      addError("Cette conversation a expiré. Renvoyez votre demande pour en commencer une nouvelle.");
    } else addError(error.message);
  } finally {
    if (isCurrent()) {
      // Outils lancés dont le résultat n'est jamais arrivé : on ne sait pas s'ils ont réussi
      for (const card of toolCards) {
        card.className = "tool-card level-medium";
        card.replaceChildren(icon("⚠"), ` ${card.dataset.label} : résultat non reçu`);
      }
      thinking?.remove();
      thinking = null;
      controller = null;
      setBusy(false);
      input.focus();
    }
  }
}

function finishToolCard(card, result) {
  card.className = `tool-card ${result.success ? "done" : "failed"}`;
  card.replaceChildren(
    icon(result.success ? "✔" : "✖"),
    ` ${toolLabel(result.name)}`,
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
