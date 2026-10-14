import datetime

from pydantic import BaseModel, ConfigDict


class InterviewSlots(BaseModel):
    """Créneaux d'entretien encore libres à une date donnée."""

    model_config = ConfigDict(frozen=True)

    date: datetime.date
    # Heures au format HH:MM ; liste vide si la date n'a aucun créneau
    slots: list[str]
