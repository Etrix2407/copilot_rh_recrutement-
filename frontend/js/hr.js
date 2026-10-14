// Page « Questions RH » : réponse de l'assistant et encadré des sources.

import { postJson, retryDelay } from "./api.js";
import { clearInvalid, clearStatus, el, markInvalid, showStatus } from "./dom.js";

const form = document.getElementById("hr-form");
const question = document.getElementById("hr-question");
const submitButton = document.getElementById("hr-submit");
const status = document.getElementById("hr-status");
const result = document.getElementById("hr-result");

export function initHr() {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    ask();
  });
  question.addEventListener("input", () => clearInvalid(question));
  // Comme pour le CV et le chat, un exemple remplit seulement le champ : on peut le relire avant d'envoyer
  for (const chip of form.querySelectorAll("[data-question]")) {
    chip.addEventListener("click", () => {
      question.value = chip.dataset.question;
      clearInvalid(question);
      question.focus();
    });
  }
}

let busy = false;

async function ask() {
  // Une seule question à la fois : un double clic n'envoie pas deux demandes
  if (busy) return;
  const text = question.value.trim();
  if (!text) {
    showStatus(status, "Écrivez votre question avant de l'envoyer.", { kind: "error" });
    markInvalid(question);
    return;
  }
  clearInvalid(question);

  busy = true;
  submitButton.disabled = true;
  result.hidden = true;
  showStatus(status, "Recherche dans les politiques RH…", { kind: "loading" });
  try {
    const answer = await postJson("/api/rag/ask", { question: text });
    clearStatus(status);
    render(answer);
  } catch (error) {
    showStatus(status, error.message, { kind: "error", onRetry: ask, retryAfter: retryDelay(error) });
  } finally {
    busy = false;
    submitButton.disabled = false;
  }
}

function render(answer) {
  const heading = el("h3", { text: "Réponse", attrs: { tabindex: "-1" } });
  const children = [heading, el("p", { text: answer.answer })];
  if (answer.sources.length) {
    children.push(
      el("div", { className: "sources" }, [
        el("h3", { text: "Sources" }),
        el("ul", {}, answer.sources.map((source) =>
          el("li", {}, [el("strong", { text: source.title }), el("br"), source.text]),
        )),
      ]),
    );
  }
  result.replaceChildren(...children);
  result.hidden = false;
  // Le clavier et le lecteur d'écran arrivent directement sur la réponse
  heading.focus();
}
