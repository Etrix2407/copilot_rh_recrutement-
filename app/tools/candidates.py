"""Outil de l'agent pour suivre les candidats (absent du cahier des charges, exigé par le pilier 3)."""

from app.models.candidate import Candidate, CandidateStatus
from app.services.candidate_store import CandidateNotFoundError, CandidateStore, InvalidStatusTransitionError
from app.services.text import normalize_name, quote_for_llm

# Statuts en français, pour les messages lus par le LLM puis repris dans ses réponses
STATUS_LABELS = {
    CandidateStatus.NEW: "nouveau",
    CandidateStatus.ANALYZED: "CV analysé",
    CandidateStatus.INTERVIEW_SCHEDULED: "entretien planifié",
    CandidateStatus.ACCEPTED: "retenu",
    CandidateStatus.REJECTED: "refusé",
}


class AmbiguousCandidateError(Exception):
    """Plusieurs dossiers correspondent ; le message dit au LLM comment départager."""


def update_candidate_status(store: CandidateStore, candidate: str, status: CandidateStatus) -> dict[str, str]:
    """Met à jour le statut d'un candidat, désigné par son identifiant, son email ou son nom complet.

    Renvoie un dictionnaire au même format que book_interview : le LLM reçoit
    toujours un résultat lisible, jamais une exception. Le statut est déjà validé par
    l'appelant (app/services/agent_tools.py). Les noms cités dans les messages viennent
    des CVs ou du LLM : ils sont neutralisés (quote_for_llm) avant d'être renvoyés au LLM.
    """
    try:
        found = find_candidate(store, candidate)
        updated = store.update_status(found.id, status)
    except CandidateNotFoundError:
        return {"statut": "ERREUR", "message": f"Aucun candidat trouvé pour {quote_for_llm(candidate)}."}
    except InvalidStatusTransitionError as exc:
        return {
            "statut": "ERREUR",
            "message": (
                f"Passage du statut « {STATUS_LABELS[exc.current]} » "
                f"au statut « {STATUS_LABELS[exc.target]} » interdit."
            ),
        }
    except AmbiguousCandidateError as exc:
        return {"statut": "ERREUR", "message": str(exc)}
    return {
        "statut": "SUCCES",
        "message": f"Statut de {quote_for_llm(updated.name)} passé à « {STATUS_LABELS[updated.status]} ».",
    }


def find_candidate(store: CandidateStore, candidate: str) -> Candidate:
    """Cherche par identifiant, puis par email, puis par nom (sans tenir compte de la casse).

    L'email départage les homonymes : sans lui, un nom partagé n'aurait aucune issue.
    Lève AmbiguousCandidateError si l'email ou le nom désigne plusieurs dossiers.
    """
    try:
        return store.get(candidate)
    except CandidateNotFoundError:
        pass
    by_email = store.find_all_by_email(candidate)
    if len(by_email) > 1:
        raise AmbiguousCandidateError(
            f"Plusieurs candidats ont l'email {quote_for_llm(candidate)} : "
            "précisez le nom ou l'identifiant du candidat."
        )
    if by_email:
        return by_email[0]
    wanted = normalize_name(candidate)
    matches = [c for c in store.list_all() if normalize_name(c.name) == wanted]
    if len(matches) > 1:
        raise AmbiguousCandidateError(
            f"Plusieurs candidats s'appellent {quote_for_llm(candidate)} : précisez l'email du candidat."
        )
    if not matches:
        raise CandidateNotFoundError(candidate)
    return matches[0]
