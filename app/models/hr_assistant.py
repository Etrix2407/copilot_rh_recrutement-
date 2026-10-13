from pydantic import BaseModel, ConfigDict, Field


class PolicyExcerpt(BaseModel):
    """Une politique RH retrouvée dans la base vectorielle."""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    text: str


class HRAnswer(BaseModel):
    """Réponse de l'assistant RH, avec les extraits sur lesquels elle s'appuie."""

    model_config = ConfigDict(frozen=True)

    answer: str
    sources: list[PolicyExcerpt]


class HRAnswerDraft(BaseModel):
    """Réponse brute demandée au LLM, avant le contrôle des sources par le service.

    Les descriptions des champs servent de consignes au LLM.
    """

    model_config = ConfigDict(frozen=True)

    answered: bool = Field(
        description="true uniquement si les extraits fournis contiennent explicitement la réponse, sinon false."
    )
    answer: str = Field(
        description="Réponse factuelle en français, fondée uniquement sur les extraits. Chaîne vide si answered vaut false."
    )
    source_ids: list[str] = Field(
        description="Identifiants (rh_doc_xx) des extraits réellement utilisés pour répondre. Liste vide si answered vaut false."
    )
