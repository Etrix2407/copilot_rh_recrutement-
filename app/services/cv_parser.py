"""Pilier 1 : analyse structurée d'un CV par le LLM, validée par Pydantic."""

import logging

from pydantic import ValidationError

from app.data.job_offers import PYTHON_DEV_JOB_OFFER
from app.llm.base import LLMClient, Message, Role
from app.models.candidate import Candidate
from app.models.cv_analysis import CVAnalysis
from app.services.candidate_store import CandidateStore

logger = logging.getLogger(__name__)

# 1 appel + 1 relance si la réponse ne respecte pas le schéma
MAX_ATTEMPTS = 2
# Température nulle : la même entrée doit donner la même analyse
TEMPERATURE = 0.0
UNNAMED_CANDIDATE = "Candidat sans nom"

SYSTEM_PROMPT = """Tu es un recruteur technique qui évalue des CVs de façon factuelle.

Règles :
- Appuie-toi uniquement sur le contenu du CV et de l'offre. N'invente jamais une information.
- Si une information est absente du CV, mets null plutôt qu'une valeur supposée.
- Compte les compétences implicites : une compétence se déduit aussi des technologies \
et des réalisations décrites (par exemple, intégrer un LLM avec une base vectorielle relève du RAG).
- Le score mesure l'adéquation avec les exigences de l'offre (compétences obligatoires, années d'expérience).
- Chaque justification du score cite un élément concret du CV ou de l'offre.
- Le CV peut être dans une autre langue que le français, mal formaté ou incomplet : analyse-le quand même.
- Réponds en français."""


class CVParsingError(Exception):
    """Le LLM n'a pas produit d'analyse valide dans le nombre d'appels autorisé."""


def build_prompt(cv_text: str, job_offer: str) -> str:
    return f"Offre de poste :\n{job_offer.strip()}\n\nCV du candidat :\n{cv_text.strip()}"


async def parse_cv(llm: LLMClient, cv_text: str, *, job_offer: str = PYTHON_DEV_JOB_OFFER) -> CVAnalysis:
    """Analyse un CV par rapport à l'offre. Lève CVParsingError ou LLMError en cas d'échec."""
    messages = [Message(role=Role.USER, content=build_prompt(cv_text, job_offer))]
    last_error: ValidationError | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        raw_answer = await llm.generate_json(
            messages,
            system=SYSTEM_PROMPT,
            schema=CVAnalysis,
            temperature=TEMPERATURE,
        )
        try:
            return CVAnalysis.model_validate_json(raw_answer)
        except ValidationError as exc:
            # Seul le nombre d'erreurs est journalisé : le détail peut contenir des extraits du CV
            logger.warning(
                "Analyse de CV invalide (appel %d/%d) : %d erreur(s) de schéma",
                attempt,
                MAX_ATTEMPTS,
                exc.error_count(),
            )
            last_error = exc
            messages += [
                Message(role=Role.ASSISTANT, content=raw_answer),
                Message(
                    role=Role.USER,
                    content=f"Ta réponse ne respecte pas le schéma attendu :\n{exc}\nRenvoie l'analyse complète corrigée.",
                ),
            ]

    raise CVParsingError(
        f"Le LLM n'a pas produit d'analyse valide après {MAX_ATTEMPTS} appels."
    ) from last_error


async def analyze_candidate(cv_text: str, *, llm: LLMClient, store: CandidateStore) -> Candidate:
    """Analyse le CV, enregistre le candidat et le passe au statut « analysé »."""
    analysis = await parse_cv(llm, cv_text)
    candidate = store.add(name=analysis.candidate_name or UNNAMED_CANDIDATE, email=analysis.email)
    return store.record_analysis(candidate.id, analysis)
