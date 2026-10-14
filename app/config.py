"""Configuration centralisée, lue depuis le fichier .env."""

import datetime
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Modèle d'embedding fourni par ChromaDB, sans dépendance supplémentaire
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


class Settings(BaseSettings):
    # env_ignore_empty : une variable laissée vide (« DEMO_DATE= ») vaut comme absente
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True)

    # Fournisseurs pour lesquels un adaptateur existe dans app/llm/
    llm_provider: Literal["gemini"] = "gemini"
    llm_model: str
    llm_api_key: SecretStr

    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    # Dossier où ChromaDB sauvegarde la base vectorielle
    chroma_path: str = "chroma_db"

    # Base SQLite des candidats (dossier ignoré par Git)
    database_path: str = "storage/candidates.db"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # Autres origines autorisées à appeler l'API depuis un navigateur. Vide par défaut :
    # l'interface est servie par l'API elle-même, donc depuis la même origine.
    cors_origins: list[str] = []
    # Noms d'hôte acceptés dans l'en-tête Host (protection contre le « DNS rebinding »)
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    # Requêtes déclenchant le LLM (analyse, RAG, chat) autorisées par minute et par adresse IP : protège le quota.
    # Une requête peut entraîner plusieurs appels au LLM (relance du parsing, outils de l'agent).
    llm_requests_per_minute: int = Field(default=10, ge=1)
    # Date du jour donnée à l'agent (format AAAA-MM-JJ). Vide : la vraie date. Utile pour la démo et les
    # tests, car l'agenda du cahier des charges ne contient que les 15 et 16/10/2026
    demo_date: datetime.date | None = None


@lru_cache
def get_settings() -> Settings:
    """Charge la configuration une seule fois et la réutilise ensuite."""
    return Settings()
