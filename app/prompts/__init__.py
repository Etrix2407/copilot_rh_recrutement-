"""Prompts système des services LLM, gardés dans des fichiers texte pour être relus et modifiés sans toucher au code."""

from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent


@cache
def load_prompt(name: str) -> str:
    """Renvoie le contenu de app/prompts/<name>.txt, sans le saut de ligne final."""
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8").removesuffix("\n")
