"""Exécution des outils de l'agent de qualification : validation des arguments et garde-fous.

Les garde-fous de sécurité vivent ici, pas dans le prompt système que le LLM peut ignorer :
seuls les outils connus sont exécutés, leurs arguments sont validés, la recherche de
créneaux est imposée avant la réservation, le dossier du candidat est vérifié avant
de prendre un créneau (le store contrôle ensuite les transitions de statut), et chaque
demande de l'utilisateur permet au plus une réservation et un changement de statut.
"""

import logging
import sqlite3
import time
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.llm.base import Message, ToolCall, ToolResult
from app.models.agent import ToolResultEvent
from app.models.candidate import Candidate, CandidateStatus
from app.models.cv_analysis import EMAIL_PATTERN
from app.services.candidate_store import (
    ALLOWED_TRANSITIONS,
    CandidateNotFoundError,
    CandidateStore,
    InvalidStatusTransitionError,
)
from app.services.text import normalize_name, quote_for_llm
from app.tools.candidates import STATUS_LABELS, AmbiguousCandidateError, find_candidate, update_candidate_status
from app.tools.definitions import BOOK_INTERVIEW_TOOL, SEARCH_SLOTS_TOOL, UPDATE_STATUS_TOOL
from app.tools.interviews import book_interview, search_interview_slots

logger = logging.getLogger(__name__)

SUCCESS = "SUCCES"

# Appels réussis autorisés par message de l'utilisateur : un LLM détourné ne peut ni vider
# l'agenda ni changer le statut de tous les candidats en une seule demande
MAX_BOOKINGS_PER_REQUEST = 1
MAX_STATUS_UPDATES_PER_REQUEST = 1
_MAX_SUCCESSES_PER_REQUEST = {
    BOOK_INTERVIEW_TOOL: MAX_BOOKINGS_PER_REQUEST,
    UPDATE_STATUS_TOOL: MAX_STATUS_UPDATES_PER_REQUEST,
}

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
    email: Annotated[str, StringConstraints(pattern=EMAIL_PATTERN, max_length=254)]


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


# Plafond par message de l'utilisateur : (appels réussis autorisés, message pour le LLM, résumé pour l'humain)
_PER_REQUEST_LIMITS: dict[str, tuple[int, str, str]] = {
    BOOK_INTERVIEW_TOOL: (
        MAX_BOOKINGS_PER_REQUEST,
        "Entretien non réservé : une seule réservation par demande.",
        "Réservation non faite : une seule réservation par demande.",
    ),
    UPDATE_STATUS_TOOL: (
        MAX_STATUS_UPDATES_PER_REQUEST,
        "Statut non modifié : un seul changement de statut par demande de l'utilisateur.",
        "Statut non modifié : un seul changement de statut par demande.",
    ),
}


@dataclass(frozen=True)
class ToolOutcome:
    """Résultat d'un outil : le contenu renvoyé au LLM, et le résumé affiché à l'humain.

    Le contenu s'adresse au LLM (noms d'outils, de paramètres, consignes) ; le résumé de la
    carte d'outil est en français courant, sans nom technique.
    """

    result: ToolResult
    summary: str

    @property
    def succeeded(self) -> bool:
        content = self.result.content
        return isinstance(content, list) or content.get("statut") == SUCCESS

    def to_event(self) -> ToolResultEvent:
        return ToolResultEvent(name=self.result.name, success=self.succeeded, summary=self.summary)


class _Refusal(Exception):
    """Appel refusé avant toute action : un message pour le LLM, un résumé pour l'humain."""

    def __init__(self, message: str, summary: str) -> None:
        super().__init__(message)
        self.message = message
        self.summary = summary


def run_tool(
    call: ToolCall,
    *,
    store: CandidateStore,
    searched_dates: Set[str],
    successes: Mapping[str, int] | None = None,
) -> ToolOutcome:
    """Exécute un appel d'outil du LLM et journalise son résultat, sans donnée personnelle.

    searched_dates : dates dont le LLM a déjà VU le résultat de recherche (voir searched_dates_in).
    successes : appels déjà réussis pendant ce message de l'utilisateur, par nom d'outil
    (voir ToolOutcome.succeeded), pour les plafonds par demande.
    """
    started = time.perf_counter()
    try:
        content, summary = _dispatch(call, store=store, searched_dates=searched_dates, successes=successes or {})
    except _Refusal as refusal:
        content, summary = _error(refusal.message), refusal.summary
    duration_ms = (time.perf_counter() - started) * 1000
    # Ni valeurs des arguments ni messages : ils contiennent des noms et des emails (données personnelles)
    logger.info(
        "Outil %s (arguments : %s) -> %s (%.1f ms)",
        call.name,
        ", ".join(sorted(call.arguments)) or "aucun",
        _outcome(content),
        duration_ms,
    )
    return ToolOutcome(result=ToolResult(call_id=call.id, name=call.name, content=content), summary=summary)


def searched_dates_in(history: Sequence[Message]) -> set[str]:
    """Dates déjà cherchées avec succès : la réservation n'est autorisée que pour elles.

    Seul l'historique déjà envoyé au LLM compte : une recherche faite dans la même série
    d'appels que la réservation n'ouvre pas ce droit, car le LLM n'en a pas vu le résultat
    et ne peut pas savoir si le créneau demandé était libre. Une recherche refusée (arguments invalides)
    n'ouvre pas ce droit. Les résultats d'un message TOOL sont dans le même ordre que les appels du
    message qui le précède.
    """
    dates: set[str] = set()
    # Longueurs différentes voulues : chaque message est associé au suivant
    for calls_message, results_message in zip(history, history[1:], strict=False):
        # Un point de reprise partiel peut avoir moins de résultats que d'appels
        for call, result in zip(calls_message.tool_calls, results_message.tool_results, strict=False):
            if call.name == SEARCH_SLOTS_TOOL and isinstance(result.content, list):
                dates.add(str(call.arguments.get("date")))
    return dates


def _dispatch(
    call: ToolCall, *, store: CandidateStore, searched_dates: Set[str], successes: Mapping[str, int]
) -> tuple[list[str] | dict[str, str], str]:
    """Exécute l'outil demandé ; renvoie le contenu pour le LLM et le résumé pour l'humain.

    Un outil inconnu, des arguments invalides ou un plafond atteint lèvent _Refusal (une ERREUR
    pour le LLM) : une panne du stockage remonte comme toute erreur interne.
    """
    schema = _ARGUMENTS.get(call.name)
    if schema is None:
        raise _Refusal(f"Outil inconnu : {call.name!r}.", "Action inconnue de l'assistant.")
    # Seule la validation des arguments est protégée : une erreur pendant l'exécution n'est pas
    # la faute des arguments (une ValidationError peut aussi venir d'une ligne illisible en base)
    try:
        args = schema.model_validate(call.arguments)
    except ValidationError as exc:
        # Avec des alias, « loc » contient le nom vu par le LLM (ex. « heure »), pas le nom Python
        fields = ", ".join(str(error["loc"][0]) for error in exc.errors() if error["loc"])
        raise _Refusal(
            f"Arguments invalides : {fields or 'format incorrect'}.", "Demande incomplète ou mal formée."
        ) from None
    if call.name in _PER_REQUEST_LIMITS:
        limit, message, summary = _PER_REQUEST_LIMITS[call.name]
        if successes.get(call.name, 0) >= limit:
            raise _Refusal(message, summary)

    match args:
        case _SearchArgs():
            # Copie : le LLM ne doit pas recevoir une référence vers l'agenda lui-même
            slots = list(search_interview_slots(args.date))
            return slots, _slots_summary(len(slots))
        case _BookArgs():
            return _book(args, store=store, searched_dates=searched_dates)
        case _StatusArgs():
            result = update_candidate_status(store, args.candidate, args.status)
            if result["statut"] != SUCCESS:
                return result, "Statut non modifié."
            return result, f"Statut du candidat : {STATUS_LABELS[args.status]}."
    raise AssertionError(f"Outil sans exécution : {call.name}")


def _slots_summary(count: int) -> str:
    match count:
        case 0:
            return "Aucun créneau libre"
        case 1:
            return "1 créneau trouvé"
        case _:
            return f"{count} créneaux trouvés"


def _book(booking: _BookArgs, *, store: CandidateStore, searched_dates: Set[str]) -> tuple[dict[str, str], str]:
    """Réserve après avoir vérifié la recherche préalable et le dossier du candidat, puis le planifie.

    Lève _Refusal si la réservation est refusée avant de prendre le créneau.
    """
    if booking.date not in searched_dates:
        raise _Refusal(
            f"Vérifie d'abord les créneaux libres avec {SEARCH_SLOTS_TOOL} pour cette date, "
            "puis réserve un créneau de la liste obtenue.",
            "Réservation reportée : l'assistant vérifie d'abord les créneaux.",
        )

    # Le dossier est contrôlé AVANT de prendre le créneau : un candidat déjà planifié,
    # retenu ou refusé, ou un nom et un email incohérents, ne consomment pas un créneau de l'agenda
    candidate = _find_booked_candidate(store, booking)
    if candidate is not None and CandidateStatus.INTERVIEW_SCHEDULED not in ALLOWED_TRANSITIONS[candidate.status]:
        label = STATUS_LABELS[candidate.status]
        raise _Refusal(
            f"Entretien non réservé : le dossier de {quote_for_llm(candidate.name)} est au statut « {label} ».",
            f"Réservation non faite : dossier au statut « {label} ».",
        )

    result = book_interview(booking.candidate_name, booking.date, booking.time, booking.email)
    if result["statut"] != SUCCESS:
        return result, "Créneau déjà pris ou indisponible."
    if candidate is None:
        # Cas du test officiel 3 : la réservation est valable même sans dossier enregistré
        logger.info("Réservation pour un candidat sans dossier : statut non suivi")
        follow_up = "Aucun dossier candidat correspondant : statut non suivi."
    else:
        follow_up = _schedule(store, candidate)
    return {**result, FOLLOW_UP_KEY: follow_up}, f"{result['message']} {follow_up}"


def _schedule(store: CandidateStore, candidate: Candidate) -> str:
    """Passe le dossier en « entretien planifié » après la réservation ; renvoie le suivi du dossier."""
    try:
        store.update_status(candidate.id, CandidateStatus.INTERVIEW_SCHEDULED)
    except (CandidateNotFoundError, InvalidStatusTransitionError, sqlite3.Error) as exc:
        # Le dossier a été supprimé, a changé de statut depuis la vérification, ou la base est
        # indisponible : le créneau est déjà pris, la réservation reste donc valable, seul le
        # suivi du dossier échoue
        logger.warning("Réservation faite mais dossier candidat non mis à jour (%s)", type(exc).__name__)
        return "Dossier candidat modifié, supprimé ou inaccessible : statut non mis à jour."
    return "Statut du candidat : entretien planifié."


def _find_booked_candidate(store: CandidateStore, booking: _BookArgs) -> Candidate | None:
    """Retrouve le dossier par email et nom, sinon par nom s'il est unique.

    Un email peut être partagé par plusieurs dossiers (noms différents) : parmi eux, seul
    celui dont le nom correspond est retenu.
    Renvoie None si aucun dossier ne correspond (réservation sans suivi, test officiel 3).
    Lève _Refusal si le nom et l'email désignent des dossiers incohérents, ou si plusieurs
    dossiers correspondent : le créneau irait peut-être au mauvais candidat.
    """
    mismatch = _Refusal(
        "Entretien non réservé : le nom et l'email ne correspondent pas au même dossier candidat. "
        "Vérifie le nom et l'email du candidat.",
        "Réservation non faite : le nom et l'email ne correspondent pas au même dossier.",
    )
    by_email = store.find_all_by_email(booking.email)
    if by_email:
        wanted = normalize_name(booking.candidate_name)
        same_name = [candidate for candidate in by_email if normalize_name(candidate.name) == wanted]
        if not same_name:
            raise mismatch
        if len(same_name) > 1:
            raise _Refusal(
                "Entretien non réservé : plusieurs dossiers portent ce nom et cet email. "
                "Le dossier doit être choisi par un recruteur.",
                "Réservation non faite : plusieurs dossiers correspondent, un recruteur doit choisir.",
            )
        return same_name[0]
    try:
        by_name = find_candidate(store, booking.candidate_name)
    except CandidateNotFoundError:
        return None
    except AmbiguousCandidateError:
        raise _Refusal(
            "Entretien non réservé : plusieurs dossiers portent ce nom. Précise l'email du candidat.",
            "Réservation non faite : plusieurs dossiers portent ce nom.",
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
