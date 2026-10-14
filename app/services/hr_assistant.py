"""Pilier 2 : assistant RH qui répond uniquement à partir des politiques internes (RAG)."""

import asyncio

from app.llm.base import LLMClient
from app.models.hr_assistant import HRAnswer, HRAnswerDraft, PolicyExcerpt
from app.prompts import load_prompt
from app.services.policy_index import PolicyIndex
from app.services.prompt_safety import as_data
from app.services.structured_output import generate_validated

# Nombre de politiques transmises au LLM (sur 4)
TOP_K = 3
# Température nulle : réponses factuelles et constantes
TEMPERATURE = 0.0
# Formulation imposée par le cahier des charges : renvoyée par le code, jamais rédigée par le LLM
REFUSAL = "La politique interne ne précise pas ce point."

SYSTEM_PROMPT = load_prompt("hr_assistant")


def build_prompt(question: str, excerpts: list[PolicyExcerpt]) -> str:
    context = "\n\n".join(f"[{excerpt.id}] {excerpt.title}\n{excerpt.text}" for excerpt in excerpts)
    question_block = as_data("question", question)
    return f"Extraits des politiques internes :\n\n{context}\n\nQuestion du collaborateur :\n{question_block}"


async def ask_hr_policies(question: str, *, llm: LLMClient, index: PolicyIndex) -> HRAnswer:
    """Répond à la question à partir des politiques RH. Lève InvalidLLMOutputError ou LLMError en cas d'échec."""
    # La recherche (embedding + ChromaDB) est synchrone : on la sort de la boucle d'événements
    excerpts = await asyncio.to_thread(index.search, question, limit=TOP_K)
    draft = await generate_validated(
        llm,
        build_prompt(question, excerpts),
        system=SYSTEM_PROMPT,
        schema=HRAnswerDraft,
        temperature=TEMPERATURE,
    )

    # Seuls les extraits réellement transmis au LLM peuvent servir de sources
    sources = [excerpt for excerpt in excerpts if excerpt.id in draft.source_ids]
    if not draft.answered or not sources or not draft.answer.strip():
        return HRAnswer(answer=REFUSAL, sources=[])
    return HRAnswer(answer=draft.answer, sources=sources)
