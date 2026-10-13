"""Accès typé aux objets partagés créés au démarrage (voir create_app)."""

from typing import Annotated

from fastapi import Depends, Request

from app.llm.base import LLMClient
from app.services.candidate_store import CandidateStore
from app.services.policy_index import PolicyIndex


def get_llm_client(request: Request) -> LLMClient:
    return request.app.state.llm_client


def get_candidate_store(request: Request) -> CandidateStore:
    return request.app.state.candidate_store


def get_policy_index(request: Request) -> PolicyIndex:
    return request.app.state.policy_index


LLMClientDep = Annotated[LLMClient, Depends(get_llm_client)]
CandidateStoreDep = Annotated[CandidateStore, Depends(get_candidate_store)]
PolicyIndexDep = Annotated[PolicyIndex, Depends(get_policy_index)]
