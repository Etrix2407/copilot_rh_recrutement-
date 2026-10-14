// Navigation par onglets : l'adresse (#cv, #candidats…) permet le bouton « Retour » et les favoris.

import { initCandidates, refreshCandidates } from "./candidates.js";
import { initChat } from "./chat.js";
import { initCv } from "./cv.js";
import { initHr } from "./hr.js";

const PANELS = ["cv", "candidats", "rh", "entretien"];

function showPanel(id, { focus }) {
  const current = PANELS.includes(id) ? id : PANELS[0];
  for (const panel of PANELS) {
    document.getElementById(panel).hidden = panel !== current;
    const link = document.getElementById(`tab-${panel}`);
    if (panel === current) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  // Le titre de l'onglet du navigateur (et de l'historique) suit la rubrique affichée
  const heading = document.querySelector(`#${current} h2`);
  document.title = `${heading.textContent} — Copilot RH`;
  // Le tableau est rechargé à chaque visite : un statut changé par l'agent y apparaît aussitôt
  if (current === "candidats") refreshCandidates();
  // Au clavier ou au lecteur d'écran, on arrive directement sur le titre de la rubrique
  if (focus) {
    heading.setAttribute("tabindex", "-1");
    heading.focus();
  }
}

initCv();
initCandidates();
initHr();
initChat();

window.addEventListener("hashchange", () => showPanel(location.hash.slice(1), { focus: true }));
showPanel(location.hash.slice(1), { focus: false });
