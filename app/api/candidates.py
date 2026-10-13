from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.api.dependencies import CandidateStoreDep, LLMClientDep
from app.llm.base import LLMError
from app.models.candidate import Candidate
from app.services.cv_parser import CVParsingError, analyze_candidate
from app.services.cv_reader import CVReadError, read_cv_file

router = APIRouter(prefix="/api/candidates", tags=["candidates"])


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
        try:
            cv_text = read_cv_file(file.filename or "", await file.read())
        except CVReadError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    else:
        cv_text = text or ""
        if not cv_text.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Le texte du CV est vide.")

    try:
        return await analyze_candidate(cv_text, llm=llm, store=store)
    except (LLMError, CVParsingError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
