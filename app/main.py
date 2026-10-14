"""Point d'entrée de l'API : uvicorn app.main:create_app --factory --reload"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TypedDict

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction
from chromadb.config import Settings as ChromaSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import agent, candidates, health, interviews, rag
from app.api.errors import install_error_handlers
from app.api.rate_limit import RateLimiter
from app.config import Settings, get_settings
from app.data.hr_policies import HR_POLICIES
from app.llm.base import LLMClient
from app.llm.factory import create_llm_client
from app.logging_config import configure_logging
from app.security import SecurityMiddleware
from app.services.agent_chat import ConversationStore
from app.services.candidate_store import CandidateStore
from app.services.policy_index import PolicyIndex, create_embedding_function

logger = logging.getLogger(__name__)

# Interface web (HTML/CSS/JS sans build), servie à la racine par l'API elle-même
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


class AppState(TypedDict):
    """Objets partagés par toutes les requêtes, lus par les routes via request.state."""

    llm_client: LLMClient
    candidate_store: CandidateStore
    policy_index: PolicyIndex
    conversation_store: ConversationStore
    rate_limiter: RateLimiter
    settings: Settings


def create_app(
    settings: Settings | None = None,
    *,
    embedding_function: EmbeddingFunction[Documents] | None = None,
) -> FastAPI:
    """Construit l'application.

    Les tests passent leurs propres Settings (pour ne pas dépendre du .env)
    et un faux embedding (pour ne pas télécharger le modèle).
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[AppState]:
        # Créés une seule fois au démarrage ; Starlette les copie dans request.state à chaque requête
        llm_client = create_llm_client(settings)
        candidate_store = CandidateStore(settings.database_path)
        try:
            # Dans le try : si l'indexation échoue, le client LLM et la base sont quand même fermés
            policy_index = build_policy_index(settings, embedding_function)
            logger.info("API démarrée (LLM : %s / %s)", settings.llm_provider, settings.llm_model)
            yield {
                "llm_client": llm_client,
                "candidate_store": candidate_store,
                "policy_index": policy_index,
                "conversation_store": ConversationStore(),
                "rate_limiter": RateLimiter(settings.llm_requests_per_minute),
                "settings": settings,
            }
        finally:
            # Fermeture garantie, même après une erreur au démarrage ou pendant le fonctionnement
            await llm_client.aclose()
            candidate_store.close()

    app = FastAPI(title="Copilot RH Recrutement", lifespan=lifespan)
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityMiddleware, allowed_hosts=settings.allowed_hosts, allowed_origins=settings.cors_origins)
    app.include_router(health.router)
    app.include_router(candidates.router)
    app.include_router(rag.router)
    app.include_router(interviews.router)
    app.include_router(agent.router)
    # Monté en dernier : les routes /api et /docs restent prioritaires
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


def build_policy_index(
    settings: Settings,
    embedding_function: EmbeddingFunction[Documents] | None,
) -> PolicyIndex:
    """Ouvre la base vectorielle et y indexe les politiques RH du cahier des charges."""
    # anonymized_telemetry=False : ChromaDB n'envoie pas de statistiques d'usage
    client = chromadb.PersistentClient(path=settings.chroma_path, settings=ChromaSettings(anonymized_telemetry=False))
    index = PolicyIndex(client, embedding_function or create_embedding_function(settings.embedding_model))
    # Au premier lancement, le modèle d'embedding par défaut est téléchargé (environ 80 Mo)
    index.index(HR_POLICIES)
    logger.info("%d politiques RH indexées (%s)", index.count(), settings.embedding_model)
    return index
