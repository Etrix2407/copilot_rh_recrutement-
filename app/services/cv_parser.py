"""Pilier 1 : analyse structurée d'un CV par le LLM, validée par Pydantic."""

from app.data.job_offers import PYTHON_DEV_JOB_OFFER
from app.llm.base import LLMClient
from app.models.candidate import Candidate
from app.models.cv_analysis import CVAnalysis
from app.prompts import load_prompt
from app.services.candidate_store import CandidateStore
from app.services.prompt_safety import as_data
from app.services.structured_output import generate_validated

# Température nulle : la même entrée doit donner la même analyse
TEMPERATURE = 0.0
UNNAMED_CANDIDATE = "Candidat sans nom"
# Le nom revient au LLM dans les résultats d'outils : sa longueur est bornée
MAX_NAME_LENGTH = 100

SYSTEM_PROMPT = load_prompt("cv_parser")


def build_prompt(cv_text: str, job_offer: str) -> str:
    return f"Offre de poste :\n{job_offer.strip()}\n\nCV du candidat :\n{as_data('cv', cv_text)}"


async def parse_cv(llm: LLMClient, cv_text: str, *, job_offer: str = PYTHON_DEV_JOB_OFFER) -> CVAnalysis:
    """Analyse un CV par rapport à l'offre. Lève InvalidLLMOutputError ou LLMError en cas d'échec."""
    return await generate_validated(
        llm,
        build_prompt(cv_text, job_offer),
        system=SYSTEM_PROMPT,
        schema=CVAnalysis,
        temperature=TEMPERATURE,
    )


async def analyze_candidate(cv_text: str, *, llm: LLMClient, store: CandidateStore) -> Candidate:
    """Analyse le CV, enregistre le candidat et le passe au statut « analysé ».

    Un CV dont l'email est déjà connu met à jour ce candidat au lieu d'en créer un doublon :
    sinon, l'agent ne saurait plus quel « Jean Dupont » passer en entretien planifié.
    """
    analysis = await parse_cv(llm, cv_text)
    name = " ".join((analysis.candidate_name or "").split())[:MAX_NAME_LENGTH] or UNNAMED_CANDIDATE
    existing = store.find_by_email(analysis.email) if analysis.email else None
    # Même email ET même nom : c'est le même candidat. Un email partagé par deux personnes ne fusionne rien.
    if existing is not None and _same_name(existing.name, name):
        return store.replace_analysis(existing.id, name=name, analysis=analysis)
    candidate = store.add(name=name, email=analysis.email)
    return store.record_analysis(candidate.id, analysis)


def _same_name(first: str, second: str) -> bool:
    """Compare deux noms sans tenir compte de la casse ni des espaces multiples."""
    return " ".join(first.split()).casefold() == " ".join(second.split()).casefold()
