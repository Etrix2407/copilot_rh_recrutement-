"""Point d'entrée de l'API : uvicorn app.main:create_app --factory --reload"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction
from chromadb.config import Settings as ChromaSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import candidates, health, rag
from app.config import Settings, get_settings
from app.data.hr_policies import HR_POLICIES
from app.llm.factory import create_llm_client
from app.logging_config import configure_logging
from app.services.candidate_store import CandidateStore
from app.services.policy_index import PolicyIndex, create_embedding_function

logger = logging.getLogger(__name__)


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
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Objets partagés par toutes les requêtes, créés une seule fois au démarrage
        app.state.llm_client = create_llm_client(settings)
        app.state.candidate_store = CandidateStore()
        app.state.policy_index = build_policy_index(settings, embedding_function)
        logger.info("API démarrée (LLM : %s / %s)", settings.llm_provider, settings.llm_model)
        yield
        await app.state.llm_client.aclose()

    app = FastAPI(title="Copilot RH Recrutement", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(candidates.router)
    app.include_router(rag.router)
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
