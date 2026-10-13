"""Schéma de l'analyse d'un CV : il est envoyé au LLM pour imposer le format de sa réponse.

Les descriptions des champs servent de consignes au LLM.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EducationLevel(StrEnum):
    # Valeurs fixées par le plan de développement
    BAC = "bac"
    BAC_PLUS_2 = "bac+2"
    BAC_PLUS_3 = "bac+3"
    BAC_PLUS_5 = "bac+5"
    DOCTORATE = "doctorat"
    OTHER = "autre"


class CVAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_name: str | None = Field(description="Nom complet du candidat, null s'il n'apparaît pas dans le CV.")
    email: str | None = Field(description="Adresse email du candidat, null si absente du CV.")
    key_skills: list[str] = Field(
        description="Compétences clés du candidat, y compris celles qui se déduisent de ses expériences."
    )
    years_of_experience: float | None = Field(
        ge=0,
        description="Années d'expérience professionnelle, null si impossible à déterminer.",
    )
    education_level: EducationLevel | None = Field(
        description="Plus haut niveau d'études, null si absent du CV. Un bootcamp correspond à « autre »."
    )
    match_score: int = Field(ge=0, le=100, description="Adéquation du candidat avec l'offre, de 0 à 100.")
    score_justifications: list[str] = Field(
        min_length=1,
        description="Raisons factuelles du score, chacune s'appuyant sur le CV et l'offre.",
    )
    red_flags: list[str] = Field(
        description="Points de vigilance : exigences de l'offre non couvertes, incohérences, trous dans le parcours."
    )
