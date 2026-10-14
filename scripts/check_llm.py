"""Vérifie que le LLM configuré dans .env répond, en passant par la couche d'abstraction.

Usage, depuis la racine du projet : python -m scripts.check_llm
"""

import asyncio
import sys

from app.config import ConfigurationError, get_settings
from app.llm.base import LLMError
from app.llm.factory import create_llm_client


async def main() -> int:
    try:
        settings = get_settings()
    except ConfigurationError as exc:
        print(exc)
        return 1
    client = create_llm_client(settings)
    try:
        answer = await client.generate("Réponds uniquement par le mot : ok")
    except LLMError as exc:
        print(f"Échec de l'appel à {settings.llm_provider} / {settings.llm_model} : {exc}")
        print("Vérifiez LLM_MODEL et LLM_API_KEY dans .env ; une erreur 429 signifie que le quota est atteint.")
        return 1
    finally:
        await client.aclose()
    print(f"{settings.llm_provider} / {settings.llm_model} -> {answer.strip()}")
    return 0


if __name__ == "__main__":
    # Accents lisibles même dans une console Windows qui n'est pas en UTF-8
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
