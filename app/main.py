"""Point d'entrée de l'API : uvicorn app.main:app --reload"""

from fastapi import FastAPI

from app.api import health

app = FastAPI(title="Copilot RH Recrutement")
app.include_router(health.router)
