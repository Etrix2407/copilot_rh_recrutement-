"""Vérifie que le LLM configuré dans .env répond, en passant par la couche d'abstraction.

Usage, depuis la racine du projet : python -m scripts.check_llm
"""

import asyncio

from app.config import get_settings
from app.llm.factory import create_llm_client


async def main() -> None:
    settings = get_settings()
    client = create_llm_client(settings)
    try:
        answer = await client.generate("Réponds uniquement par le mot : ok")
    finally:
        await client.aclose()
    print(f"{settings.llm_provider} / {settings.llm_model} -> {answer.strip()}")


if __name__ == "__main__":
    asyncio.run(main())
