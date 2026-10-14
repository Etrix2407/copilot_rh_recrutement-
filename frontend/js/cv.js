// Page « Analyser un CV ».

import { getJson, postForm, retryDelay } from "./api.js";
import { clearInvalid, clearStatus, el, icon, markInvalid, showStatus } from "./dom.js";
import { EDUCATION_LABELS, scoreLevel, yearsLabel } from "./labels.js";

// Mêmes limites que le serveur : vérifiées avant l'envoi pour répondre tout de suite
export const MAX_FILE_BYTES = 2_000_000;
const ALLOWED_EXTENSIONS = [".pdf", ".txt"];

const form = document.getElementById("cv-form");
const fileInput = document.getElementById("cv-file");
const clearFileButton = document.getElementById("cv-file-clear");
const textInput = document.getElementById("cv-text");
const submitButton = document.getElementById("cv-submit");
const status = document.getElementById("cv-status");
const result = document.getElementById("cv-result");

export function initCv() {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    analyze();
  });
  fileInput.addEventListener("change", () => {
    clearInvalid(fileInput, textInput);
    clearFileButton.hidden = !fileInput.files.length;
    // Un fichier refusé est signalé dès qu'il est choisi, sans attendre l'envoi
    const problem = fileInput.files.length ? fileProblem(fileInput.files[0]) : null;
    if (problem) showFileError(problem);
    else clearStatus(status);
  });
  clearFileButton.addEventListener("click", () => {
    clearFile();
    clearStatus(status);
    fileInput.focus();
  });
  textInput.addEventListener("input", () => clearInvalid(textInput));
  loadSamples();
}

function clearFile() {
  fileInput.value = "";
  clearFileButton.hidden = true;
  clearInvalid(fileInput);
}

async function loadSamples() {
  const container = document.getElementById("cv-samples");
  try {
    for (const sample of await getJson("/api/candidates/samples")) {
      const button = el("button", { className: "chip", text: sample.label, attrs: { type: "button" } });
      button.addEventListener("click", () => {
        clearFile();
        clearInvalid(textInput);
        textInput.value = sample.text.trim();
        textInput.focus();
      });
      container.append(button);
    }
  } catch {
    // Les exemples sont un confort : sans eux, la page reste utilisable
    document.getElementById("cv-samples-block").hidden = true;
  }
}

// Message clair si le fichier ne peut pas être envoyé, sinon null
export function fileProblem(file) {
  const name = file.name.toLowerCase();
  if (!ALLOWED_EXTENSIONS.some((extension) => name.endsWith(extension))) {
    return "Ce fichier n'est ni un PDF ni un fichier .txt. Choisissez un autre fichier ou collez le texte du CV.";
  }
  if (file.size > MAX_FILE_BYTES) {
    return "Ce fichier est trop lourd (2 Mo au maximum). Choisissez un fichier plus léger ou collez le texte du CV.";
  }
  return null;
}

function showFileError(message) {
  showStatus(status, message, { kind: "error" });
  markInvalid(fileInput);
}

let busy = false;

async function analyze() {
  // Une seule analyse à la fois : un double clic n'envoie pas deux demandes
  if (busy) return;
  const file = fileInput.files[0];
  const text = textInput.value.trim();
  clearInvalid(fileInput, textInput);
  if (!file && !text) {
    showStatus(status, "Choisissez un fichier ou collez le texte du CV.", { kind: "error" });
    markInvalid(textInput);
    return;
  }
  if (file && text) {
    showStatus(status, "Choisissez soit un fichier, soit du texte, pas les deux.", { kind: "error" });
    markInvalid(fileInput);
    return;
  }
  const problem = file ? fileProblem(file) : null;
  if (problem) {
    showFileError(problem);
    return;
  }

  const data = new FormData();
  if (file) data.append("file", file);
  else data.append("text", text);

  busy = true;
  submitButton.disabled = true;
  result.hidden = true;
  showStatus(status, "Analyse en cours… cela prend quelques secondes.", { kind: "loading" });
  let failed = false;
  try {
    const candidate = await postForm("/api/candidates/parse", data);
    clearStatus(status);
    // Le fichier est analysé : le champ est vidé pour le CV suivant
    clearFile();
    showResult(candidate);
  } catch (error) {
    failed = true;
    showStatus(status, error.message, { kind: "error", onRetry: analyze, retryAfter: retryDelay(error) });
  } finally {
    busy = false;
    submitButton.disabled = false;
  }
  // Après une erreur, le clavier revient sur le bouton d'envoi (il était désactivé pendant l'analyse)
  if (failed) submitButton.focus();
}

function showResult(candidate) {
  const nodes = renderAnalysis(candidate);
  result.replaceChildren(...nodes);
  result.hidden = false;
  nodes[0].focus();
}

// Analyse complète d'un candidat (aussi affichée depuis le tableau des candidats).
// Le premier élément est le titre (nom), focalisable pour y amener le clavier.
export function renderAnalysis(candidate) {
  const analysis = candidate.analysis;
  const level = scoreLevel(analysis.match_score);
  const fill = el("div", { className: `gauge-fill ${level.className}` });
  fill.style.width = `${analysis.match_score}%`;

  const facts = el("dl", { className: "facts" }, [
    el("dt", { text: "Email" }),
    el("dd", { text: analysis.email ?? "Non indiqué" }),
    el("dt", { text: "Expérience" }),
    el("dd", { text: analysis.years_of_experience == null ? "Non indiquée" : yearsLabel(analysis.years_of_experience) }),
    el("dt", { text: "Formation" }),
    el("dd", { text: EDUCATION_LABELS[analysis.education_level] ?? "Non indiquée" }),
  ]);

  return [
    el("h3", { text: candidate.name, attrs: { tabindex: "-1" } }),
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
      el("h3", {}, [icon("⚠"), " Points de vigilance"]),
      list(analysis.red_flags, "", "Aucun point de vigilance."),
    ]),
  ];
}

function list(items, className = "", emptyText = "") {
  if (!items.length) return el("p", { className: "empty", text: emptyText });
  return el("ul", { className }, items.map((item) => el("li", { text: item })));
}
