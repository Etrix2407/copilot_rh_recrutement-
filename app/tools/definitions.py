"""Description des outils de l'agent pour le LLM.

La description de chaque outil reprend sa docstring : c'est elle que le LLM lit
pour décider quand l'appeler.
"""

import inspect
from collections.abc import Callable

from app.llm.base import ToolDefinition
from app.models.candidate import CandidateStatus
from app.tools.candidates import update_candidate_status
from app.tools.interviews import book_interview, search_interview_slots

DATE_PARAMETER = {"type": "string", "description": "Date au format YYYY-MM-DD"}


def _define(function: Callable[..., object], properties: dict[str, dict[str, object]]) -> ToolDefinition:
    return ToolDefinition(
        name=function.__name__,
        # Première ligne de la docstring : les détails d'implémentation ne concernent pas le LLM
        description=(inspect.getdoc(function) or "").splitlines()[0],
        parameters={"type": "object", "properties": properties, "required": list(properties)},
    )


TOOL_DEFINITIONS: list[ToolDefinition] = [
    _define(search_interview_slots, {"date": DATE_PARAMETER}),
    _define(
        book_interview,
        {
            "candidate_name": {"type": "string", "description": "Nom complet du candidat"},
            "date": DATE_PARAMETER,
            "time": {"type": "string", "description": "Heure au format HH:MM, prise dans les créneaux disponibles"},
            "email": {"type": "string", "description": "Email du candidat, qui reçoit l'invitation"},
        },
    ),
    _define(
        update_candidate_status,
        {
            "candidate": {"type": "string", "description": "Identifiant ou nom complet du candidat"},
            "status": {
                "type": "string",
                "enum": [status.value for status in CandidateStatus],
                "description": "Nouveau statut du candidat",
            },
        },
    ),
]
