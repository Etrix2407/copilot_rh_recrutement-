"""Mesure les critères d'évaluation avec le vrai LLM et affiche un rapport Markdown pour le README.

Usage, depuis la racine du projet : python -m scripts.evaluate
Consomme du quota : environ 25 appels au LLM, espacés (compter 4 à 5 minutes).
"""

import asyncio
import copy
import datetime
import sys
import tempfile
import time
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings
from app.data.agenda import RECRUITER_AGENDA
from app.data.candidates import SAMPLE_CANDIDATE_1, SAMPLE_CANDIDATE_2
from app.data.hr_policies import HR_POLICIES
from app.llm.base import LLMClient, LLMError
from app.llm.factory import create_llm_client
from app.models.agent import ErrorEvent, TokenEvent, ToolStartEvent
from app.services.agent_chat import ConversationStore, chat
from app.services.candidate_store import CandidateStore
from app.services.cv_parser import parse_cv
from app.services.hr_assistant import REFUSAL, ask_hr_policies
from app.services.policy_index import PolicyIndex, create_embedding_function
from app.services.structured_output import InvalidLLMOutputError

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
# Pause entre deux appels : le quota gratuit de Gemini limite le nombre de requêtes par minute
PAUSE_SECONDS = 5
EVALUATION_DATE = datetime.date(2026, 10, 14)
AGENT_REQUEST = (
    "Trouve-moi un créneau le 2026-10-15 pour réserver un entretien avec Jean Dupont (jean.dupont@email.com)"
)


async def evaluate_cvs(llm: LLMClient) -> list[str]:
    cvs = [("Jean Dupont (officiel)", SAMPLE_CANDIDATE_1), ("Sophie Martin (officiel)", SAMPLE_CANDIDATE_2)]
    cvs += [(path.stem, path.read_text(encoding="utf-8")) for path in sorted((FIXTURES_DIR / "cvs").glob("*.txt"))]

    rows = ["| CV | JSON valide | Score | Compétences | Points de vigilance |", "|---|---|---|---|---|"]
    valid = 0
    for name, text in cvs:
        await asyncio.sleep(PAUSE_SECONDS)
        try:
            analysis = await parse_cv(llm, text)
        except (InvalidLLMOutputError, LLMError) as exc:
            rows.append(f"| {name} | ❌ ({type(exc).__name__}) | — | — | — |")
            continue
        valid += 1
        rows.append(
            f"| {name} | ✅ | {analysis.match_score} | {len(analysis.key_skills)} | {len(analysis.red_flags)} |"
        )
    return [f"**{valid}/{len(cvs)} JSON valides**", "", *rows]


async def evaluate_rag(llm: LLMClient) -> list[str]:
    questions = (FIXTURES_DIR / "rag_trap_questions.txt").read_text(encoding="utf-8").splitlines()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as path:
        chroma = chromadb.PersistentClient(path=path, settings=ChromaSettings(anonymized_telemetry=False))
        index = PolicyIndex(chroma, create_embedding_function(get_settings().embedding_model))
        index.index(HR_POLICIES)

        rows = ["| Question piège | Refusée |", "|---|---|"]
        refused = 0
        for question in questions:
            await asyncio.sleep(PAUSE_SECONDS)
            try:
                answer = await ask_hr_policies(question, llm=llm, index=index)
            except (InvalidLLMOutputError, LLMError) as exc:
                rows.append(f"| {question} | ❌ ({type(exc).__name__}) |")
                continue
            ok = answer.answer == REFUSAL and not answer.sources
            refused += ok
            rows.append(f"| {question} | {'✅' if ok else '❌ ' + answer.answer} |")
    return [f"**{refused}/{len(questions)} refus corrects, aucune règle inventée attendue**", "", *rows]


async def evaluate_latency(llm: LLMClient) -> list[str]:
    """Délais du chat de l'agent (test officiel 3), mesurés côté serveur sans le réseau du navigateur."""
    initial_agenda = copy.deepcopy(RECRUITER_AGENDA)
    # Fenêtre de quota vidée : la mesure ne doit pas inclure l'attente d'une relance
    await asyncio.sleep(60)
    store = CandidateStore()
    started = time.perf_counter()
    first_event = first_word = None
    try:
        async for event in chat(
            AGENT_REQUEST,
            conversation_id="evaluation",
            history=[],
            llm=llm,
            store=store,
            conversations=ConversationStore(),
            # Date fixe : l'agenda du cahier des charges ne contient que les 15 et 16/10/2026
            today=EVALUATION_DATE,
        ):
            elapsed = time.perf_counter() - started
            # Seul ce que l'utilisateur voit compte : l'événement start (id de conversation) est invisible
            if isinstance(event, ToolStartEvent | TokenEvent):
                first_event = first_event or elapsed
            if isinstance(event, TokenEvent):
                first_word = first_word or elapsed
            if isinstance(event, ErrorEvent):
                return [f"Mesure impossible : {event.message}"]
    finally:
        store.close()
        RECRUITER_AGENDA.clear()
        RECRUITER_AGENDA.update(initial_agenda)
    total = time.perf_counter() - started
    return [
        "| Mesure | Délai |",
        "|---|---|",
        f"| Premier retour (carte d'outil) | {first_event:.1f} s |" if first_event else "| Premier retour | — |",
        f"| Premier mot de la réponse | {first_word:.1f} s |" if first_word else "| Premier mot | — |",
        f"| Réponse complète | {total:.1f} s |",
    ]


async def main() -> None:
    # La console Windows n'est pas en UTF-8 par défaut : le rapport contient des accents et des ✅
    sys.stdout.reconfigure(encoding="utf-8")
    settings = get_settings()
    llm = create_llm_client(settings)
    try:
        sections = [
            ("Robustesse de l'extraction", await evaluate_cvs(llm)),
            ("Étanchéité du RAG", await evaluate_rag(llm)),
            ("Délais du chat (test officiel 3)", await evaluate_latency(llm)),
        ]
    finally:
        await llm.aclose()

    print(f"_Mesuré avec {settings.llm_provider} / {settings.llm_model}._\n")
    for title, lines in sections:
        print(f"### {title}\n")
        print("\n".join(lines), end="\n\n")


if __name__ == "__main__":
    asyncio.run(main())
