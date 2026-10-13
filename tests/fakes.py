"""Doublures de test partagées : faux client LLM et générateur de PDF."""

from collections.abc import Sequence

from pydantic import BaseModel

from app.llm.base import LLMError, Message


class FakeLLMClient:
    """Faux LLM : renvoie les réponses prévues, dans l'ordre, et garde la trace des appels.

    Une réponse de type LLMError est levée au lieu d'être renvoyée.
    """

    def __init__(self) -> None:
        self.json_answers: list[str | LLMError] = []
        self.json_calls: list[dict[str, object]] = []

    async def generate(self, prompt: str) -> str:
        return "ok"

    async def generate_json(
        self,
        messages: Sequence[Message],
        *,
        system: str,
        schema: type[BaseModel],
        temperature: float,
    ) -> str:
        self.json_calls.append(
            {"messages": list(messages), "system": system, "schema": schema, "temperature": temperature}
        )
        answer = self.json_answers.pop(0)
        if isinstance(answer, LLMError):
            raise answer
        return answer


def build_pdf(text: str) -> bytes:
    """Construit un PDF d'une page contenant le texte donné (ASCII), ou aucun texte si vide."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_offset = len(pdf)
    pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    pdf += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref_offset)
    return pdf
