"""Outil de l'agent pour suivre les candidats (absent du cahier des charges, exigé par le pilier 3)."""

from app.models.candidate import Candidate, CandidateStatus
from app.services.candidate_store import CandidateNotFoundError, CandidateStore, InvalidStatusTransitionError


class AmbiguousCandidateError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"Plusieurs candidats s'appellent {name!r} : précisez l'email du candidat.")


def update_candidate_status(store: CandidateStore, candidate: str, status: str) -> dict:
    """Met à jour le statut d'un candidat, désigné par son identifiant, son email ou son nom complet.

    Renvoie un dictionnaire au même format que book_interview : le LLM reçoit
    toujours un résultat lisible, jamais une exception.
    """
    try:
        new_status = CandidateStatus(status)
    except ValueError:
        allowed = ", ".join(s.value for s in CandidateStatus)
        return {"statut": "ERREUR", "message": f"Statut inconnu : {status!r}. Valeurs possibles : {allowed}."}

    try:
        found = find_candidate(store, candidate)
        updated = store.update_status(found.id, new_status)
    except CandidateNotFoundError:
        return {"statut": "ERREUR", "message": f"Aucun candidat trouvé pour {candidate!r}."}
    except (InvalidStatusTransitionError, AmbiguousCandidateError) as exc:
        return {"statut": "ERREUR", "message": str(exc)}
    return {"statut": "SUCCES", "message": f"Statut de {updated.name} passé à {updated.status.value!r}."}


def find_candidate(store: CandidateStore, candidate: str) -> Candidate:
    """Cherche par identifiant, puis par email, puis par nom (sans tenir compte de la casse).

    L'email départage les homonymes : sans lui, un nom partagé n'aurait aucune issue.
    """
    try:
        return store.get(candidate)
    except CandidateNotFoundError:
        pass
    by_email = store.find_by_email(candidate)
    if by_email is not None:
        return by_email
    wanted = normalize_name(candidate)
    matches = [c for c in store.list_all() if normalize_name(c.name) == wanted]
    if len(matches) > 1:
        raise AmbiguousCandidateError(candidate)
    if not matches:
        raise CandidateNotFoundError(candidate)
    return matches[0]


def normalize_name(name: str) -> str:
    """Nom comparable : espaces multiples et casse ignorés (« jean  DUPONT » désigne bien Jean Dupont)."""
    return " ".join(name.split()).casefold()
