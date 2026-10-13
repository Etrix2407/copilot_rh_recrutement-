"""Point d'entrée de l'API : uvicorn app.main:create_app --factory --reload"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import candidates, health
from app.config import Settings, get_settings
from app.llm.factory import create_llm_client
from app.logging_config import configure_logging
from app.services.candidate_store import CandidateStore

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construit l'application. Les tests passent leurs propres Settings pour ne pas dépendre du .env."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Objets partagés par toutes les requêtes, créés une seule fois au démarrage
        app.state.llm_client = create_llm_client(settings)
        app.state.candidate_store = CandidateStore()
        logger.info("API démarrée (LLM : %s / %s)", settings.llm_provider, settings.llm_model)
        yield

    app = FastAPI(title="Copilot RH Recrutement", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(candidates.router)
    return app
