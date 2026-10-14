"""Schéma de l'analyse d'un CV : il est envoyé au LLM pour imposer le format de sa réponse.

Les descriptions des champs servent de consignes au LLM.
"""

import re
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


class EducationLevel(StrEnum):
    # Valeurs fixées par le plan de développement
    BAC = "bac"
    BAC_PLUS_2 = "bac+2"
    BAC_PLUS_3 = "bac+3"
    BAC_PLUS_5 = "bac+5"
    DOCTORATE = "doctorat"
    OTHER = "autre"


# Forme minimale d'un email, partagée par l'analyse des CVs et les arguments de l'agent ;
# le reste (« Non renseigné », vide…) est traité comme absent
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
_EMAIL = re.compile(EMAIL_PATTERN)

# Texte non vide (les espaces autour sont retirés)
_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CVAnalysis(BaseModel):
    # Schéma strict : un champ inconnu ou un texte vide rend la réponse invalide (et déclenche la relance)
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Pas de longueur maximale ici (un nom trop long ferait échouer toute l'analyse) : le nom est tronqué
    # à l'enregistrement, car il revient ensuite au LLM dans les résultats d'outils
    candidate_name: str | None = Field(description="Nom complet du candidat, null s'il n'apparaît pas dans le CV.")
    email: str | None = Field(description="Adresse email du candidat, null si absente du CV.")
    key_skills: list[_Text] = Field(
        description="Compétences clés du candidat, y compris celles qui se déduisent de ses expériences."
    )
    years_of_experience: float | None = Field(
        ge=0,
        le=80,
        allow_inf_nan=False,
        description="Années d'expérience professionnelle, null si impossible à déterminer.",
    )
    education_level: EducationLevel | None = Field(
        description="Plus haut niveau d'études, null si absent du CV. Un bootcamp correspond à « autre »."
    )
    # strict : un score envoyé en texte (« 85 ») est une réponse invalide, pas un nombre deviné
    match_score: int = Field(strict=True, ge=0, le=100, description="Adéquation du candidat avec l'offre, de 0 à 100.")
    score_justifications: list[_Text] = Field(
        min_length=1,
        description="Raisons factuelles du score, chacune s'appuyant sur le CV et l'offre.",
    )
    red_flags: list[_Text] = Field(
        description="Points de vigilance : exigences de l'offre non couvertes, incohérences, trous dans le parcours."
    )

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, email: str | None) -> str | None:
        """Email en minuscules sans espaces, ou None s'il est absent ou invalide : il sert à reconnaître un candidat."""
        cleaned = (email or "").strip().lower()
        return cleaned if _EMAIL.match(cleaned) else None
