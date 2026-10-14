// Page « Candidats » : tableau triable par score et par statut.

import { deleteResource, getJson } from "./api.js";
import { clearStatus, el, showStatus } from "./dom.js";
import { STATUS_LABELS, STATUS_ORDER, scoreLevel } from "./labels.js";

const status = document.getElementById("candidates-status");
const tableContainer = document.getElementById("candidates-table");
const sortSelect = document.getElementById("candidates-sort");

let candidates = [];

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
  showStatus(status, "Chargement des candidats…", { kind: "loading" });
  try {
    candidates = await getJson("/api/candidates");
    clearStatus(status);
    render();
  } catch (error) {
    tableContainer.replaceChildren();
    showStatus(status, error.message, { kind: "error", onRetry: refreshCandidates });
  }
}

function score(candidate) {
  return candidate.analysis?.match_score ?? -1;
}

function render() {
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
    return el("tr", {}, [
      el("th", { text: candidate.name, attrs: { scope: "row" } }),
      el("td", { className: "number" }, [scoreCell]),
      el("td", {}, [el("span", { className: `badge ${candidate.status}`, text: STATUS_LABELS[candidate.status] })]),
      el("td", { text: candidate.email ?? "—" }),
      el("td", {}, [deleteButton(candidate)]),
    ]);
  });

  tableContainer.replaceChildren(
    el("table", {}, [
      el("caption", { className: "visually-hidden", text: "Liste des candidats" }),
      el("thead", {}, [
        el("tr", {}, ["Nom", "Score", "Statut", "Email", "Action"].map((title) => el("th", { text: title, attrs: { scope: "col" } }))),
      ]),
      el("tbody", {}, rows),
    ]),
  );
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
    try {
      await deleteResource(`/api/candidates/${encodeURIComponent(candidate.id)}`);
      candidates = candidates.filter((other) => other.id !== candidate.id);
      showStatus(status, `${candidate.name} a été supprimé.`);
      render();
    } catch (error) {
      if (error.status === 404) {
        // Déjà supprimé (autre onglet, redémarrage…) : la ligne disparaît aussi
        candidates = candidates.filter((other) => other.id !== candidate.id);
        render();
      } else {
        button.disabled = false;
      }
      showStatus(status, error.message, { kind: "error" });
    }
  });
  return button;
}
