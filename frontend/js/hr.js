// Page « Questions RH » : réponse de l'assistant et encadré des sources.

import { postJson } from "./api.js";
import { clearStatus, el, showStatus } from "./dom.js";

const form = document.getElementById("hr-form");
const question = document.getElementById("hr-question");
const status = document.getElementById("hr-status");
const result = document.getElementById("hr-result");

export function initHr() {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    ask();
  });
  for (const chip of form.querySelectorAll("[data-question]")) {
    chip.addEventListener("click", () => {
      question.value = chip.dataset.question;
      ask();
    });
  }
}

async function ask() {
  const text = question.value.trim();
  if (!text) {
    showStatus(status, "Écrivez votre question avant de l'envoyer.", { kind: "error" });
    question.focus();
    return;
  }

  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  result.hidden = true;
  showStatus(status, "Recherche dans les politiques RH…", { kind: "loading" });
  try {
    const answer = await postJson("/api/rag/ask", { question: text });
    clearStatus(status);
    render(answer);
  } catch (error) {
    showStatus(status, error.message, { kind: "error", onRetry: ask });
  } finally {
    button.disabled = false;
  }
}

function render(answer) {
  const children = [el("h3", { text: "Réponse" }), el("p", { text: answer.answer })];
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
}
