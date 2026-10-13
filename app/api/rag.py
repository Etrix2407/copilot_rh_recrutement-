from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import LLMClientDep, PolicyIndexDep
from app.llm.base import LLMError
from app.models.hr_assistant import HRAnswer
from app.services.hr_assistant import ask_hr_policies
from app.services.structured_output import InvalidLLMOutputError

router = APIRouter(prefix="/api/rag", tags=["rag"])


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, description="Question sur les politiques RH")


@router.post("/ask")
async def ask(request: AskRequest, llm: LLMClientDep, index: PolicyIndexDep) -> HRAnswer:
    """Répond à une question RH à partir des politiques internes, avec les extraits utilisés."""
    try:
        return await ask_hr_policies(request.question, llm=llm, index=index)
    except (LLMError, InvalidLLMOutputError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
