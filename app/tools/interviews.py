"""Outils de l'agent pour les entretiens (cahier des charges, section 6).

Repris du cahier des charges : seuls les noms sont traduits ; docstrings,
comportement et valeurs de retour sont identiques.
"""

from app.data.agenda import RECRUITER_AGENDA


# rechercher_creneaux_entretien
def search_interview_slots(date: str) -> list[str]:
    """Retourne la liste des heures disponibles pour un entretien à une date donnée (format YYYY-MM-DD)."""
    return RECRUITER_AGENDA.get(date, [])


# reserver_entretien (candidat_nom → candidate_name, heure → time)
def book_interview(candidate_name: str, date: str, time: str, email: str) -> dict:
    """Réserve un créneau d'entretien pour un candidat et confirme la réservation."""
    if date in RECRUITER_AGENDA and time in RECRUITER_AGENDA[date]:
        RECRUITER_AGENDA[date].remove(time)
        return {"statut": "SUCCES", "message": f"Entretien confirmé pour {candidate_name} le {date} à {time}. Invitation envoyée à {email}."}
    return {"statut": "ERREUR", "message": "Créneau indisponible."}
