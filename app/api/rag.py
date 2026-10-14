from fastapi import APIRouter, Request

from app.api.dependencies import LLMClientDep, PolicyIndexDep
from app.api.errors import llm_unavailable
from app.api.rate_limit import enforce_llm_rate_limit
from app.llm.base import LLMError
from app.models.hr_assistant import AskRequest, HRAnswer
from app.services.hr_assistant import ask_hr_policies
from app.services.structured_output import InvalidLLMOutputError

router = APIRouter(prefix="/api/rag", tags=["rag"])


@router.post("/ask")
async def ask(body: AskRequest, request: Request, llm: LLMClientDep, index: PolicyIndexDep) -> HRAnswer:
    """Répond à une question RH à partir des politiques internes, avec les extraits utilisés."""
    # Compté seulement pour une demande valide, juste avant l'appel au LLM
    enforce_llm_rate_limit(request)
    try:
        return await ask_hr_policies(body.question, llm=llm, index=index)
    except (LLMError, InvalidLLMOutputError) as exc:
        raise llm_unavailable(exc) from exc
