"""Accès typé aux objets partagés créés au démarrage (état de lifespan, voir create_app).

Fonctions asynchrones : FastAPI les exécute sur la boucle d'événements, sans passer par un thread.
"""

from typing import Annotated

from fastapi import Depends, Request

from app.config import Settings
from app.llm.base import LLMClient
from app.services.agent_chat import ConversationStore
from app.services.candidate_store import CandidateStore
from app.services.policy_index import PolicyIndex


async def get_llm_client(request: Request) -> LLMClient:
    return request.state.llm_client


async def get_candidate_store(request: Request) -> CandidateStore:
    return request.state.candidate_store


async def get_policy_index(request: Request) -> PolicyIndex:
    return request.state.policy_index


async def get_conversation_store(request: Request) -> ConversationStore:
    return request.state.conversation_store


async def get_app_settings(request: Request) -> Settings:
    return request.state.settings


LLMClientDep = Annotated[LLMClient, Depends(get_llm_client)]
CandidateStoreDep = Annotated[CandidateStore, Depends(get_candidate_store)]
PolicyIndexDep = Annotated[PolicyIndex, Depends(get_policy_index)]
ConversationStoreDep = Annotated[ConversationStore, Depends(get_conversation_store)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
