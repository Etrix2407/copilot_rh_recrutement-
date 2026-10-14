// Libellés en français courant pour les valeurs techniques de l'API.

export const STATUS_LABELS = {
  new: "Nouveau",
  analyzed: "CV analysé",
  interview_scheduled: "Entretien planifié",
  accepted: "Retenu",
  rejected: "Refusé",
};

// Ordre d'avancement, utilisé pour trier le tableau par statut
export const STATUS_ORDER = ["new", "analyzed", "interview_scheduled", "accepted", "rejected"];

export const EDUCATION_LABELS = {
  bac: "Bac",
  "bac+2": "Bac +2",
  "bac+3": "Bac +3",
  "bac+5": "Bac +5",
  doctorat: "Doctorat",
  autre: "Autre formation",
};

export const TOOL_LABELS = {
  rechercher_creneaux_entretien: "Recherche de créneaux",
  reserver_entretien: "Réservation de l'entretien",
  mettre_a_jour_statut_candidat: "Mise à jour du statut",
};

// Outil inconnu (ajouté côté serveur) : libellé générique plutôt que le nom technique
export function toolLabel(name) {
  return TOOL_LABELS[name] ?? "Action de l'assistant";
}

// « 1 an », « 1,5 an », « 3 ans » : pluriel à partir de 2, nombre écrit à la française
export function yearsLabel(years) {
  return `${years.toLocaleString("fr-FR")} ${years < 2 ? "an" : "ans"}`;
}

// Niveau du score : la couleur est toujours doublée d'un mot, pour ne pas dépendre de la vue des couleurs
export function scoreLevel(score) {
  if (score >= 70) return { className: "level-good", label: "Très bon profil" };
  if (score >= 40) return { className: "level-medium", label: "Profil moyen" };
  return { className: "level-bad", label: "Profil peu adapté" };
}
