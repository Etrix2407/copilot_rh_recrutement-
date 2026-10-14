import asyncio
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.api.dependencies import CandidateStoreDep, LLMClientDep
from app.api.errors import llm_unavailable
from app.llm.base import LLMError
from app.data.candidates import SAMPLE_CANDIDATE_1, SAMPLE_CANDIDATE_2
from app.models.candidate import Candidate, CVSample
from app.services.cv_parser import analyze_candidate
from app.services.cv_reader import MAX_CV_BYTES, CVReadError, check_cv_length, read_cv_file
from app.services.structured_output import InvalidLLMOutputError

router = APIRouter(prefix="/api/candidates", tags=["candidates"])

# Contenu identique au cahier des charges (section 5)
CV_SAMPLES = [
    CVSample(label="Jean Dupont", text=SAMPLE_CANDIDATE_1),
    CVSample(label="Sophie Martin", text=SAMPLE_CANDIDATE_2),
]


@router.get("")
def list_candidates(store: CandidateStoreDep) -> list[Candidate]:
    """Renvoie tous les candidats suivis, avec leur statut et leur analyse."""
    return store.list_all()


@router.get("/samples")
def list_cv_samples() -> list[CVSample]:
    """Renvoie les CVs d'exemple du cahier des charges, pour essayer l'analyse sans fichier."""
    return CV_SAMPLES


@router.post("/parse")
async def parse_candidate(
    llm: LLMClientDep,
    store: CandidateStoreDep,
    file: Annotated[UploadFile | None, File(description="CV au format .pdf ou .txt")] = None,
    text: Annotated[str | None, Form(description="Texte du CV collé directement")] = None,
) -> Candidate:
    """Analyse un CV (fichier ou texte), enregistre le candidat et renvoie son analyse."""
    if (file is None) == (text is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Envoyez soit un fichier, soit du texte.")

    if file is not None:
        # Refusé avant lecture : un fichier énorme n'est jamais chargé en mémoire
        if file.size is not None and file.size > MAX_CV_BYTES:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE, f"Fichier trop volumineux : {MAX_CV_BYTES // 1_000_000} Mo maximum."
            )
        try:
            # L'extraction d'un PDF est synchrone et coûteuse : elle ne doit pas bloquer les autres requêtes
            cv_text = await asyncio.to_thread(read_cv_file, file.filename or "", await file.read())
        except CVReadError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    else:
        cv_text = text or ""
        if not cv_text.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Le texte du CV est vide.")
        try:
            check_cv_length(cv_text)
        except CVReadError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    try:
        return await analyze_candidate(cv_text, llm=llm, store=store)
    except (LLMError, InvalidLLMOutputError) as exc:
        raise llm_unavailable(exc) from exc
