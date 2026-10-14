import asyncio
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile, status

from app.api.dependencies import CandidateStoreDep, ConversationStoreDep, LLMClientDep
from app.api.errors import llm_unavailable
from app.api.rate_limit import enforce_llm_rate_limit
from app.data.candidates import SAMPLE_CANDIDATE_1, SAMPLE_CANDIDATE_2
from app.llm.base import LLMError
from app.models.candidate import Candidate, CVSample
from app.services.candidate_store import CandidateNotFoundError
from app.services.cv_parser import analyze_candidate
from app.services.cv_reader import MAX_CV_BYTES, CVReaderBusyError, CVReadError, extract_cv_text
from app.services.privacy import erase_candidate
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


@router.delete("/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_candidate(
    candidate_id: str, store: CandidateStoreDep, conversations: ConversationStoreDep
) -> Response:
    """Supprime définitivement un candidat, son analyse et les conversations qui le mentionnent (RGPD)."""
    try:
        erase_candidate(candidate_id, store=store, conversations=conversations)
    except CandidateNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/parse")
async def parse_candidate(
    request: Request,
    llm: LLMClientDep,
    store: CandidateStoreDep,
    file: Annotated[UploadFile | None, File(description="CV au format .pdf ou .txt")] = None,
    text: Annotated[str | None, Form(description="Texte du CV collé directement")] = None,
) -> Candidate:
    """Analyse un CV (fichier ou texte), enregistre le candidat et renvoie son analyse."""
    # Contrôle bon marché avant de lire le fichier (déjà reçu par le serveur, mais pas encore traité)
    if file is not None and file.size is not None and file.size > MAX_CV_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"Fichier trop volumineux : {MAX_CV_BYTES // 1_000_000} Mo maximum."
        )
    content = await file.read() if file is not None else None
    if file is not None:
        # Un fichier est compté avant l'extraction : la lecture d'un PDF coûte cher, même sans appel au LLM
        enforce_llm_rate_limit(request)
    try:
        # L'extraction d'un PDF est synchrone et coûteuse : elle ne doit pas bloquer les autres requêtes
        cv_text = await asyncio.to_thread(
            extract_cv_text, filename=file.filename if file else None, content=content, text=text
        )
    except CVReadError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except CVReaderBusyError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc), headers={"Retry-After": "5"}) from exc

    if file is None:
        # Texte collé : compté seulement s'il est valide, juste avant l'appel au LLM
        enforce_llm_rate_limit(request)
    try:
        return await analyze_candidate(cv_text, llm=llm, store=store)
    except (LLMError, InvalidLLMOutputError) as exc:
        raise llm_unavailable(exc) from exc
