"""Pilier 2 : assistant RH qui répond uniquement à partir des politiques internes (RAG)."""

import asyncio

from app.llm.base import LLMClient
from app.models.hr_assistant import HRAnswer, HRAnswerDraft, PolicyExcerpt
from app.services.policy_index import PolicyIndex
from app.services.structured_output import generate_validated

# Nombre de politiques transmises au LLM (sur 4)
TOP_K = 3
# Température nulle : réponses factuelles et constantes
TEMPERATURE = 0.0
# Formulation imposée par le cahier des charges : renvoyée par le code, jamais rédigée par le LLM
REFUSAL = "La politique interne ne précise pas ce point."

SYSTEM_PROMPT = """Tu es l'assistant RH de l'entreprise. Tu réponds aux questions des collaborateurs \
uniquement à partir des extraits de politiques internes fournis.

Règles impératives :
- N'utilise aucune connaissance extérieure aux extraits : ni droit du travail, ni usages courants.
- Si l'information demandée ne figure pas explicitement dans le contexte fourni ci-dessus, \
réponds obligatoirement que la politique interne ne précise pas ce point : mets answered à false.
- Une information seulement proche ou partielle ne suffit pas : en cas de doute, answered vaut false.
- Si tu réponds, cite dans source_ids les identifiants des extraits utilisés, et reprends les chiffres exacts.
- Réponds en français, de façon concise."""


def build_prompt(question: str, excerpts: list[PolicyExcerpt]) -> str:
    context = "\n\n".join(f"[{excerpt.id}] {excerpt.title}\n{excerpt.text}" for excerpt in excerpts)
    return f"Extraits des politiques internes :\n\n{context}\n\nQuestion du collaborateur :\n{question.strip()}"


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
