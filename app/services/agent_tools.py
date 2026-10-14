"""Exécution des outils de l'agent de qualification : validation des arguments et garde-fous.

Les garde-fous de sécurité vivent ici, pas dans le prompt système que le LLM peut ignorer :
seuls les outils connus sont exécutés, leurs arguments sont validés, la recherche de
créneaux est imposée avant la réservation, et le dossier du candidat est vérifié avant
de prendre un créneau (le store contrôle ensuite les transitions de statut).
"""

import logging
import time
from collections.abc import Sequence, Set
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.llm.base import Message, ToolCall, ToolResult
from app.models.agent import ToolResultEvent
from app.models.candidate import Candidate, CandidateStatus
from app.services.candidate_store import (
    ALLOWED_TRANSITIONS,
    CandidateNotFoundError,
    CandidateStore,
    InvalidStatusTransitionError,
)
from app.tools.candidates import AmbiguousCandidateError, find_candidate, normalize_name, update_candidate_status
from app.tools.definitions import BOOK_INTERVIEW_TOOL, SEARCH_SLOTS_TOOL, UPDATE_STATUS_TOOL
from app.tools.interviews import book_interview, search_interview_slots

logger = logging.getLogger(__name__)

# Statuts en français, pour les messages lus par le LLM puis repris dans ses réponses
STATUS_LABELS = {
    CandidateStatus.NEW: "nouveau",
    CandidateStatus.ANALYZED: "CV analysé",
    CandidateStatus.INTERVIEW_SCHEDULED: "entretien planifié",
    CandidateStatus.ACCEPTED: "retenu",
    CandidateStatus.REJECTED: "refusé",
}

SUCCESS = "SUCCES"

# Réservations réussies autorisées par message de l'utilisateur : un LLM détourné ne peut pas vider l'agenda
MAX_BOOKINGS_PER_REQUEST = 1

# Clé ajoutée au résultat de book_interview renvoyé au LLM : elle lui dit si le dossier du
# candidat a suivi la réservation. Visible par le LLM, elle reste en français comme les clés
# « statut » et « message » du cahier des charges, qui ne sont pas modifiées.
FOLLOW_UP_KEY = "suivi_candidat"

# Arguments attendus de chaque outil : un LLM détourné ne peut pas passer de valeur farfelue.
# Les alias sont les noms de paramètres du cahier des charges, présentés au LLM
# (app/tools/definitions.py) : seuls eux sont acceptés, un nom Python est un argument en trop.
_Date = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
_Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class _SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: _Date


class _BookArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # candidat_nom
    candidate_name: _Name = Field(alias="candidat_nom")
    date: _Date
    # heure
    time: Annotated[str, StringConstraints(pattern=r"^\d{2}:\d{2}$")] = Field(alias="heure")
    email: Annotated[str, StringConstraints(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)]


class _StatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # candidat
    candidate: _Name = Field(alias="candidat")
    # statut
    # « Entretien planifié » n'est posé que par une réservation réussie, jamais directement par le LLM
    status: Literal[CandidateStatus.ACCEPTED, CandidateStatus.REJECTED] = Field(alias="statut")


# Schéma des arguments de chaque outil, par nom présenté au LLM
_ARGUMENTS: dict[str, type[BaseModel]] = {
    SEARCH_SLOTS_TOOL: _SearchArgs,
    BOOK_INTERVIEW_TOOL: _BookArgs,
    UPDATE_STATUS_TOOL: _StatusArgs,
}


class _BookingRefusedError(Exception):
    """Réservation refusée avant de prendre le créneau ; le message est destiné au LLM."""


def run_tool(
    call: ToolCall, *, store: CandidateStore, searched_dates: Set[str], bookings_done: int = 0
) -> ToolResult:
    """Exécute un appel d'outil du LLM et journalise son résultat, sans donnée personnelle.

    searched_dates : dates dont le LLM a déjà VU le résultat de recherche (voir searched_dates_in).
    bookings_done : réservations déjà réussies pendant ce message de l'utilisateur.
    """
    started = time.perf_counter()
    content = _dispatch(call, store=store, searched_dates=searched_dates, bookings_done=bookings_done)
    duration_ms = (time.perf_counter() - started) * 1000
    # Ni valeurs des arguments ni messages : ils contiennent des noms et des emails (données personnelles)
    logger.info(
        "Outil %s (arguments : %s) -> %s (%.1f ms)",
        call.name,
        ", ".join(sorted(call.arguments)) or "aucun",
        _outcome(content),
        duration_ms,
    )
    return ToolResult(call_id=call.id, name=call.name, content=content)


def is_successful_booking(result: ToolResult) -> bool:
    """Indique si ce résultat est une réservation réussie (pour le plafond par demande)."""
    return (
        result.name == BOOK_INTERVIEW_TOOL
        and isinstance(result.content, dict)
        and result.content.get("statut") == SUCCESS
    )


def summarize(result: ToolResult) -> ToolResultEvent:
    """Résumé lisible d'un résultat d'outil, pour la carte affichée dans le chat."""
    content = result.content
    if isinstance(content, list):
        match len(content):
            case 0:
                summary = "Aucun créneau libre"
            case 1:
                summary = "1 créneau trouvé"
            case count:
                summary = f"{count} créneaux trouvés"
        return ToolResultEvent(name=result.name, success=True, summary=summary)
    summary = content.get("message", "")
    if content.get(FOLLOW_UP_KEY):
        summary = f"{summary} {content[FOLLOW_UP_KEY]}"
    return ToolResultEvent(name=result.name, success=content.get("statut") == SUCCESS, summary=summary)


def searched_dates_in(history: Sequence[Message]) -> set[str]:
    """Dates déjà cherchées avec succès : la réservation n'est autorisée que pour elles.

    Seul l'historique déjà envoyé au LLM compte : une recherche faite dans la même série
    d'appels que la réservation n'ouvre pas ce droit, car le LLM n'en a pas vu le résultat
    et ne peut pas savoir si le créneau demandé était libre. Une recherche refusée (arguments invalides) n'ouvre pas ce droit. Les résultats d'un
    message TOOL sont dans le même ordre que les appels du message qui le précède.
    """
    dates = set()
    for calls_message, results_message in zip(history, history[1:]):
        for call, result in zip(calls_message.tool_calls, results_message.tool_results):
            if call.name == SEARCH_SLOTS_TOOL and isinstance(result.content, list):
                dates.add(str(call.arguments.get("date")))
    return dates


def _dispatch(
    call: ToolCall, *, store: CandidateStore, searched_dates: Set[str], bookings_done: int
) -> list[str] | dict[str, str]:
    """Exécute l'outil demandé.

    Seuls un outil inconnu et des arguments invalides deviennent une ERREUR pour le LLM :
    une panne du stockage remonte comme toute erreur interne.
    """
    schema = _ARGUMENTS.get(call.name)
    if schema is None:
        return _error(f"Outil inconnu : {call.name!r}.")
    # Seule la validation des arguments est protégée : une erreur pendant l'exécution n'est pas
    # la faute des arguments (une ValidationError peut aussi venir d'une ligne illisible en base)
    try:
        args = schema.model_validate(call.arguments)
    except ValidationError as exc:
        # Avec des alias, « loc » contient le nom vu par le LLM (ex. « heure »), pas le nom Python
        fields = ", ".join(str(error["loc"][0]) for error in exc.errors() if error["loc"])
        return _error(f"Arguments invalides : {fields or 'format incorrect'}.")

    match args:
        case _SearchArgs():
            # Copie : le LLM ne doit pas recevoir une référence vers l'agenda lui-même
            return list(search_interview_slots(args.date))
        case _BookArgs():
            return _book(args, store=store, searched_dates=searched_dates, bookings_done=bookings_done)
        case _StatusArgs():
            return update_candidate_status(store, args.candidate, args.status)
    raise AssertionError(f"Outil sans exécution : {call.name}")


def _book(
    booking: _BookArgs, *, store: CandidateStore, searched_dates: Set[str], bookings_done: int
) -> dict[str, str]:
    """Réserve après avoir vérifié la recherche préalable et le dossier du candidat, puis le planifie."""
    if bookings_done >= MAX_BOOKINGS_PER_REQUEST:
        return _error("Entretien non réservé : une seule réservation par demande.")
    if booking.date not in searched_dates:
        return _error(
            f"Vérifie d'abord les créneaux libres avec {SEARCH_SLOTS_TOOL} pour cette date, "
            "puis réserve un créneau de la liste obtenue."
        )

    # Le dossier est contrôlé AVANT de prendre le créneau : un candidat déjà planifié,
    # retenu ou refusé, ou un nom et un email incohérents, ne consomment pas un créneau de l'agenda
    try:
        candidate = _find_booked_candidate(store, booking)
    except _BookingRefusedError as exc:
        return _error(str(exc))
    if candidate is not None and CandidateStatus.INTERVIEW_SCHEDULED not in ALLOWED_TRANSITIONS[candidate.status]:
        return _error(
            f"Entretien non réservé : le dossier de {candidate.name} est au statut « {STATUS_LABELS[candidate.status]} »."
        )

    result = book_interview(booking.candidate_name, booking.date, booking.time, booking.email)
    if result["statut"] != SUCCESS:
        return result
    if candidate is None:
        # Cas du test officiel 3 : la réservation est valable même sans dossier enregistré
        logger.info("Réservation pour un candidat sans dossier : statut non suivi")
        return {**result, FOLLOW_UP_KEY: "Aucun dossier candidat correspondant : statut non suivi."}
    try:
        store.update_status(candidate.id, CandidateStatus.INTERVIEW_SCHEDULED)
    except (CandidateNotFoundError, InvalidStatusTransitionError) as exc:
        # Le dossier a été supprimé ou a changé de statut depuis la vérification : le créneau
        # est déjà pris, la réservation reste donc valable, seul le suivi du dossier échoue
        logger.warning("Réservation faite mais dossier candidat non mis à jour (%s)", type(exc).__name__)
        return {
            **result,
            FOLLOW_UP_KEY: "Dossier candidat modifié ou supprimé entre-temps : statut non mis à jour.",
        }
    return {**result, FOLLOW_UP_KEY: "Statut du candidat : entretien planifié."}


def _find_booked_candidate(store: CandidateStore, booking: _BookArgs) -> Candidate | None:
    """Retrouve le dossier par email (identifiant fiable), sinon par nom s'il est unique.

    Renvoie None si aucun dossier ne correspond (réservation sans suivi, test officiel 3).
    Lève _BookingRefusedError si le nom et l'email désignent des dossiers incohérents, ou si
    le nom est partagé par plusieurs dossiers : le créneau irait peut-être au mauvais candidat.
    """
    mismatch = _BookingRefusedError(
        "Entretien non réservé : le nom et l'email ne correspondent pas au même dossier candidat. "
        "Vérifie le nom et l'email du candidat."
    )
    by_email = store.find_by_email(booking.email)
    if by_email is not None:
        if normalize_name(by_email.name) != normalize_name(booking.candidate_name):
            raise mismatch
        return by_email
    try:
        by_name = find_candidate(store, booking.candidate_name)
    except CandidateNotFoundError:
        return None
    except AmbiguousCandidateError:
        raise _BookingRefusedError(
            "Entretien non réservé : plusieurs dossiers portent ce nom. Précise l'email du candidat."
        ) from None
    # Aucun dossier n'a l'email demandé (sinon il aurait été trouvé plus haut) : un email
    # enregistré sur le dossier trouvé par le nom est donc forcément différent
    if by_name.email:
        raise mismatch
    return by_name


def _error(message: str) -> dict[str, str]:
    return {"statut": "ERREUR", "message": message}


def _outcome(content: list[str] | dict[str, str]) -> str:
    """Résultat d'un outil résumé pour les logs, sans donnée personnelle."""
    if isinstance(content, list):
        return f"{len(content)} créneau(x)"
    return content.get("statut", "?")
