"""Événements du chat de l'agent, envoyés au frontend en SSE (le champ type sert de nom d'événement)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StartEvent(BaseModel):
    """Début de la réponse : l'id de la conversation, à réutiliser même si la réponse est interrompue."""

    model_config = ConfigDict(frozen=True)

    type: Literal["start"] = "start"
    conversation_id: str


class TokenEvent(BaseModel):
    """Un mot de la réponse (avec l'espace qui le suit)."""

    model_config = ConfigDict(frozen=True)

    type: Literal["token"] = "token"
    text: str


class ToolStartEvent(BaseModel):
    """Un outil est lancé."""

    model_config = ConfigDict(frozen=True)

    type: Literal["tool_start"] = "tool_start"
    name: str
    arguments: dict[str, Any]


class ToolResultEvent(BaseModel):
    """Résultat résumé d'un outil, à afficher dans sa carte."""

    model_config = ConfigDict(frozen=True)

    type: Literal["tool_result"] = "tool_result"
    name: str
    success: bool
    summary: str


class DoneEvent(BaseModel):
    """Fin de la réponse : l'id permet de poursuivre la conversation."""

    model_config = ConfigDict(frozen=True)

    type: Literal["done"] = "done"
    conversation_id: str
    answer: str


class ErrorEvent(BaseModel):
    """Problème pendant la réponse ; le flux s'arrête juste après."""

    model_config = ConfigDict(frozen=True)

    type: Literal["error"] = "error"
    message: str


AgentEvent = StartEvent | TokenEvent | ToolStartEvent | ToolResultEvent | DoneEvent | ErrorEvent


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=2000, description="Message du recruteur")
    conversation_id: str | None = Field(
        default=None, max_length=64, description="Absent pour démarrer une nouvelle conversation"
    )
