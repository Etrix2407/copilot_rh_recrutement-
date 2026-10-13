"""Configuration centralisée, lue depuis le fichier .env."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Fournisseurs pour lesquels un adaptateur existe dans app/llm/
    llm_provider: Literal["gemini"] = "gemini"
    llm_model: str
    llm_api_key: SecretStr

    embedding_model: str = "all-MiniLM-L6-v2"
    # Dossier où ChromaDB sauvegarde la base vectorielle
    chroma_path: str = "chroma_db"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # Origines autorisées à appeler l'API depuis un navigateur (5173 : serveur de dev Vite)
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    """Charge la configuration une seule fois et la réutilise ensuite."""
    return Settings()
