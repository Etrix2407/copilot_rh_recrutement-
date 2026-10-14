// Page « Candidats » : synthèse, tableau triable par score et par statut, analyse détaillée.

import { deleteResource, getJson, retryDelay } from "./api.js";
import { renderAnalysis } from "./cv.js";
import { clearStatus, el, showStatus } from "./dom.js";
import { STATUS_LABELS, STATUS_ORDER, scoreLevel } from "./labels.js";

const status = document.getElementById("candidates-status");
const summary = document.getElementById("candidates-summary");
const tableContainer = document.getElementById("candidates-table");
const sortSelect = document.getElementById("candidates-sort");
const details = document.getElementById("candidate-details");

const COLUMNS = ["Nom", "Score", "Statut", "Email", "Action"];

let candidates = [];
// Numéro de la dernière demande : une réponse plus ancienne arrivée en retard est ignorée
let latestRequest = 0;
// Boutons « Supprimer », dans l'ordre d'affichage (pour placer le focus après une suppression)
let deleteButtons = [];
// Boutons des noms, par id de candidat (le focus revient sur le nom quand on ferme son analyse)
let nameButtons = new Map();
// Candidat dont l'analyse est ouverte
let openId = null;

const SORTERS = {
  "score-desc": (a, b) => score(b) - score(a),
  "score-asc": (a, b) => score(a) - score(b),
  status: (a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) || score(b) - score(a),
  name: (a, b) => a.name.localeCompare(b.name, "fr"),
};

export function initCandidates() {
  sortSelect.addEventListener("change", render);
  document.getElementById("candidates-refresh").addEventListener("click", refreshCandidates);
}

export async function refreshCandidates() {
  const request = ++latestRequest;
  showStatus(status, "Chargement des candidats…", { kind: "loading" });
  try {
    const received = await getJson("/api/candidates");
    if (request !== latestRequest) return;
    candidates = received;
    clearStatus(status);
    render();
  } catch (error) {
    if (request !== latestRequest) return;
    candidates = [];
    closeDetails({ restoreFocus: false });
    summary.hidden = true;
    tableContainer.replaceChildren();
    showStatus(status, error.message, {
      kind: "error",
      onRetry: refreshCandidates,
      retryAfter: retryDelay(error),
    });
  }
}

function score(candidate) {
  return candidate.analysis?.match_score ?? -1;
}

function plural(count, word) {
  return `${count} ${word}${count > 1 ? "s" : ""}`;
}

// Ligne de synthèse : nombre de candidats, répartition par statut, score moyen
function renderSummary() {
  if (!candidates.length) {
    summary.replaceChildren();
    summary.hidden = true;
    return;
  }
  const items = [el("li", {}, [el("strong", { text: plural(candidates.length, "candidat") })])];
  for (const value of STATUS_ORDER) {
    const count = candidates.filter((candidate) => candidate.status === value).length;
    if (count) items.push(el("li", { text: `${STATUS_LABELS[value]} : ${count}` }));
  }
  const scores = candidates.filter((candidate) => candidate.analysis).map(score);
  if (scores.length) {
    const average = Math.round(scores.reduce((sum, value) => sum + value, 0) / scores.length);
    items.push(el("li", { text: `Score moyen : ${average} / 100` }));
  }
  summary.replaceChildren(...items);
  summary.hidden = false;
}

function render() {
  renderSummary();
  deleteButtons = [];
  nameButtons = new Map();
  // L'analyse ouverte d'un candidat qui n'est plus dans la liste est refermée
  if (openId && !candidates.some((candidate) => candidate.id === openId)) closeDetails({ restoreFocus: false });

  if (!candidates.length) {
    const link = el("a", { text: "Analyser un CV", attrs: { href: "#cv" } });
    tableContainer.replaceChildren(
      el("p", { className: "empty" }, ["Aucun candidat pour l'instant. Commencez par ", link, "."]),
    );
    return;
  }

  const rows = [...candidates].sort(SORTERS[sortSelect.value]).map((candidate) => {
    const analysis = candidate.analysis;
    const scoreCell = analysis
      ? el("span", { className: scoreLevel(analysis.match_score).className, text: `${analysis.match_score} / 100` })
      : "—";
    const remove = deleteButton(candidate);
    deleteButtons.push(remove);
    // data-label : libellé de la colonne, affiché devant chaque cellule sur petit écran
    return el("tr", {}, [
      el("th", { attrs: { scope: "row", "data-label": COLUMNS[0] } }, [nameCell(candidate)]),
      el("td", { className: "number", attrs: { "data-label": COLUMNS[1] } }, [scoreCell]),
      el("td", { attrs: { "data-label": COLUMNS[2] } }, [
        el("span", { className: `badge ${candidate.status}`, text: STATUS_LABELS[candidate.status] }),
      ]),
      el("td", { className: "email", text: candidate.email ?? "—", attrs: { "data-label": COLUMNS[3] } }),
      el("td", { attrs: { "data-label": COLUMNS[4] } }, [remove]),
    ]);
  });

  tableContainer.replaceChildren(
    el("table", {}, [
      el("caption", { className: "visually-hidden", text: "Liste des candidats" }),
      el("thead", {}, [
        el("tr", {}, COLUMNS.map((title) => el("th", { text: title, attrs: { scope: "col" } }))),
      ]),
      el("tbody", {}, rows),
    ]),
  );
}

// Nom cliquable quand une analyse existe : ouvre le détail sous le tableau
function nameCell(candidate) {
  if (!candidate.analysis) return candidate.name;
  const button = el("button", {
    className: "link-button",
    text: candidate.name,
    attrs: {
      type: "button",
      "aria-controls": "candidate-details",
      "aria-expanded": String(candidate.id === openId),
    },
  });
  button.addEventListener("click", () => openDetails(candidate));
  nameButtons.set(candidate.id, button);
  return button;
}

function openDetails(candidate) {
  openId = candidate.id;
  const nodes = renderAnalysis(candidate);
  const close = el("button", { className: "button", text: "Fermer", attrs: { type: "button" } });
  close.addEventListener("click", () => closeDetails({ restoreFocus: true }));
  details.replaceChildren(...nodes, el("div", { className: "details-actions" }, [close]));
  details.hidden = false;
  // Redessiné pour mettre à jour aria-expanded sur les noms
  render();
  // Le clavier et le lecteur d'écran arrivent sur le nom du candidat, en tête de l'analyse
  nodes[0].focus();
}

function closeDetails({ restoreFocus }) {
  const previousId = openId;
  openId = null;
  details.hidden = true;
  details.replaceChildren();
  if (!restoreFocus) return;
  render();
  // Le tableau a été redessiné : on revient sur le nouveau bouton du même candidat
  (nameButtons.get(previousId) ?? status).focus();
}

// Droit à l'effacement (RGPD) : suppression définitive, après confirmation
function deleteButton(candidate) {
  const button = el("button", {
    className: "button",
    text: "Supprimer",
    attrs: { type: "button", "aria-label": `Supprimer ${candidate.name}` },
  });
  button.addEventListener("click", async () => {
    if (!confirm(`Supprimer définitivement ${candidate.name} et son analyse ?`)) return;
    button.disabled = true;
    const position = deleteButtons.indexOf(button);
    try {
      await deleteResource(`/api/candidates/${encodeURIComponent(candidate.id)}`);
      removeCandidate(candidate, position);
      showStatus(status, `Dossier de ${candidate.name} supprimé.`);
    } catch (error) {
      if (error.status === 404) {
        // Déjà supprimé (autre onglet, redémarrage…) : la ligne disparaît aussi
        removeCandidate(candidate, position);
      } else {
        button.disabled = false;
      }
      showStatus(status, error.message, { kind: "error" });
    }
  });
  return button;
}

// Retire la ligne et place le focus sur le « Supprimer » de la ligne suivante, sinon sur le message d'état
function removeCandidate(candidate, position) {
  candidates = candidates.filter((other) => other.id !== candidate.id);
  render();
  (deleteButtons[position] ?? status).focus();
}
