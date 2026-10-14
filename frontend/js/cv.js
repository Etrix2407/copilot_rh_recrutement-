// Page « Analyser un CV ».

import { getJson, postForm } from "./api.js";
import { clearStatus, el, showStatus } from "./dom.js";
import { EDUCATION_LABELS, scoreLevel } from "./labels.js";

const form = document.getElementById("cv-form");
const fileInput = document.getElementById("cv-file");
const textInput = document.getElementById("cv-text");
const status = document.getElementById("cv-status");
const result = document.getElementById("cv-result");

export function initCv() {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    analyze();
  });
  loadSamples();
}

async function loadSamples() {
  const container = document.getElementById("cv-samples");
  try {
    for (const sample of await getJson("/api/candidates/samples")) {
      const button = el("button", { className: "chip", text: sample.label, attrs: { type: "button" } });
      button.addEventListener("click", () => {
        fileInput.value = "";
        textInput.value = sample.text.trim();
        textInput.focus();
      });
      container.append(button);
    }
  } catch {
    // Les exemples sont un confort : sans eux, la page reste utilisable
    container.closest(".samples").hidden = true;
  }
}

async function analyze() {
  const file = fileInput.files[0];
  const text = textInput.value.trim();
  if (!file && !text) {
    showStatus(status, "Choisissez un fichier ou collez le texte du CV.", { kind: "error" });
    return;
  }
  if (file && text) {
    showStatus(status, "Choisissez soit un fichier, soit du texte, pas les deux.", { kind: "error" });
    return;
  }

  const data = new FormData();
  if (file) data.append("file", file);
  else data.append("text", text);

  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  result.hidden = true;
  showStatus(status, "Analyse en cours… cela prend quelques secondes.", { kind: "loading" });
  try {
    const candidate = await postForm("/api/candidates/parse", data);
    clearStatus(status);
    renderResult(candidate);
  } catch (error) {
    showStatus(status, error.message, { kind: "error", onRetry: analyze });
  } finally {
    button.disabled = false;
  }
}

function renderResult(candidate) {
  const analysis = candidate.analysis;
  const level = scoreLevel(analysis.match_score);
  const fill = el("div", { className: `gauge-fill ${level.className}` });
  fill.style.width = `${analysis.match_score}%`;

  const facts = el("dl", { className: "facts" }, [
    el("dt", { text: "Email" }),
    el("dd", { text: analysis.email ?? "Non indiqué" }),
    el("dt", { text: "Expérience" }),
    el("dd", { text: analysis.years_of_experience == null ? "Non indiquée" : `${analysis.years_of_experience} ans` }),
    el("dt", { text: "Formation" }),
    el("dd", { text: EDUCATION_LABELS[analysis.education_level] ?? "Non indiquée" }),
  ]);

  result.replaceChildren(
    el("h3", { text: candidate.name }),
    el("div", { className: "score" }, [
      el("span", { className: `score-value ${level.className}`, text: `${analysis.match_score} / 100` }),
      el("div", {
        className: "gauge",
        attrs: { role: "img", "aria-label": `Score : ${analysis.match_score} sur 100` },
      }, [fill]),
      el("strong", { className: level.className, text: level.label }),
    ]),
    facts,
    el("h3", { text: "Compétences" }),
    list(analysis.key_skills, "tags", "Aucune compétence repérée."),
    el("h3", { text: "Pourquoi ce score" }),
    list(analysis.score_justifications),
    el("div", { className: "warnings" }, [
      el("h3", { text: "⚠ Points de vigilance" }),
      list(analysis.red_flags, "", "Aucun point de vigilance."),
    ]),
  );
  result.hidden = false;
  result.querySelector("h3").setAttribute("tabindex", "-1");
  result.querySelector("h3").focus();
}

function list(items, className = "", emptyText = "") {
  if (!items.length) return el("p", { className: "empty", text: emptyText });
  return el("ul", { className }, items.map((item) => el("li", { text: item })));
}
