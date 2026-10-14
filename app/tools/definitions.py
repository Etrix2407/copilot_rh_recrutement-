"""Description des outils de l'agent pour le LLM.

Le LLM voit les outils sous les noms et paramètres du cahier des charges (section 6) :
c'est ce qu'il appelle, ce qui apparaît dans les logs et dans l'interface. Le code Python,
lui, garde des noms anglais (voir app/tools/interviews.py).

La description de chaque outil reprend sa docstring : c'est elle que le LLM lit
pour décider quand l'appeler.
"""

import inspect
from collections.abc import Callable

from app.llm.base import ToolDefinition
from app.models.candidate import CandidateStatus
from app.tools.candidates import update_candidate_status
from app.tools.interviews import book_interview, search_interview_slots

# Noms d'outils présentés au LLM (cahier des charges, section 6 ; plan de développement, étape 4)
SEARCH_SLOTS_TOOL = "rechercher_creneaux_entretien"
BOOK_INTERVIEW_TOOL = "reserver_entretien"
UPDATE_STATUS_TOOL = "mettre_a_jour_statut_candidat"

DATE_PARAMETER = {"type": "string", "description": "Date au format YYYY-MM-DD"}


def _define(name: str, function: Callable[..., object], properties: dict[str, dict[str, object]]) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        # Première ligne de la docstring : les détails d'implémentation ne concernent pas le LLM
        description=(inspect.getdoc(function) or "").splitlines()[0],
        parameters={"type": "object", "properties": properties, "required": list(properties)},
    )


TOOL_DEFINITIONS: list[ToolDefinition] = [
    _define(SEARCH_SLOTS_TOOL, search_interview_slots, {"date": DATE_PARAMETER}),
    _define(
        BOOK_INTERVIEW_TOOL,
        book_interview,
        {
            "candidat_nom": {"type": "string", "description": "Nom complet du candidat"},
            "date": DATE_PARAMETER,
            "heure": {"type": "string", "description": "Heure au format HH:MM, prise dans les créneaux disponibles"},
            "email": {"type": "string", "description": "Email du candidat, qui reçoit l'invitation"},
        },
    ),
    _define(
        UPDATE_STATUS_TOOL,
        update_candidate_status,
        {
            "candidat": {"type": "string", "description": "Email, identifiant ou nom complet du candidat"},
            "statut": {
                "type": "string",
                # « Entretien planifié » est posé par la réservation elle-même, pas par cet outil
                "enum": [CandidateStatus.ACCEPTED.value, CandidateStatus.REJECTED.value],
                "description": "Nouveau statut du candidat",
            },
        },
    ),
]
