"""Erreurs communes aux routes et format d'erreur unique de l'API.

Toute erreur renvoie {"detail": "<message lisible en français>"} ; les erreurs de
validation ajoutent la liste technique dans « errors ».
"""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.messages import LLM_UNAVAILABLE

logger = logging.getLogger(__name__)

INTERNAL_ERROR = "Une erreur interne est survenue. Réessayez dans quelques instants."

# Messages en français pour les erreurs produites par le framework lui-même (en anglais par défaut).
# L'application ne lève jamais d'erreur 400 elle-même : toute erreur 400 vient du framework (multipart illisible…).
FRAMEWORK_ERRORS = {
    400: "Requête mal formée.",
    404: "Adresse introuvable.",
    405: "Méthode non autorisée pour cette adresse.",
}


def llm_unavailable(exc: Exception) -> HTTPException:
    """Journalise l'échec du LLM et renvoie une erreur 502 sans détail interne (modèle, réponse brute)."""
    logger.warning("Échec de l'appel au LLM : %s", exc)
    return HTTPException(status.HTTP_502_BAD_GATEWAY, LLM_UNAVAILABLE)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected_error)


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    # Ni « input » ni « ctx » : renvoyer l'entrée reçue ne sert à rien et peut être volumineux
    summary = [{key: error[key] for key in ("type", "loc", "msg") if key in error} for error in errors]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": _describe(errors[0]) if errors else "Requête invalide.", "errors": jsonable_encoder(summary)},
    )


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    # Les erreurs du framework (route inconnue, multipart illisible…) arrivent en anglais
    if exc.status_code in FRAMEWORK_ERRORS and (exc.status_code == 400 or detail == HTTPStatus(exc.status_code).phrase):
        detail = FRAMEWORK_ERRORS[exc.status_code]
    return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Le détail (trace) reste dans les logs : le client ne reçoit rien d'interne
    logger.exception("Erreur inattendue sur %s %s", request.method, request.url.path)
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": INTERNAL_ERROR})


def _describe(error: dict[str, Any]) -> str:
    """Traduit la première erreur de validation de Pydantic en phrase compréhensible."""
    # loc commence par l'emplacement (body, query…) : seul le nom du champ intéresse l'utilisateur
    field = next((str(part) for part in reversed(error.get("loc", ())) if isinstance(part, str)), "")
    context = error.get("ctx") or {}
    match error.get("type"):
        case "missing":
            problem = "champ obligatoire"
        case "string_too_long":
            problem = f"{context.get('max_length')} caractères maximum"
        case "string_too_short":
            problem = "ne doit pas être vide"
        case "date_from_datetime_parsing" | "date_parsing" | "date_type":
            problem = "date invalide, format attendu AAAA-MM-JJ"
        case "json_invalid":
            return "Le corps de la requête n'est pas un JSON valide."
        case _:
            problem = "valeur invalide"
    if field in ("", "body"):
        return f"Requête invalide : {problem}."
    return f"Champ « {field} » : {problem}."
