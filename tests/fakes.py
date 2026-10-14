"""Doublures de test partagées : faux client LLM, faux embedding, générateur de PDF, lecture SSE et agenda initial."""

import copy
import json
import re
import zlib
from collections.abc import AsyncIterator, Sequence
from typing import Any

import numpy as np
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from pydantic import BaseModel

from app.data.agenda import RECRUITER_AGENDA
from app.llm.base import LLMError, Message, ToolDefinition

# Copie de l'agenda du recruteur prise à l'import, avant tout test : référence pour vérifier qu'il est intact
INITIAL_AGENDA: dict[str, list[str]] = copy.deepcopy(RECRUITER_AGENDA)
# Créneaux initiaux du 2026-10-15, la date des tests officiels (à comparer, jamais à modifier)
INITIAL_SLOTS_2026_10_15: list[str] = INITIAL_AGENDA["2026-10-15"]


class FakeEmbeddingFunction(EmbeddingFunction[Documents]):
    """Embedding déterministe, sans modèle à télécharger : chaque mot incrémente une case du vecteur.

    Deux textes qui partagent des mots sont donc proches, ce qui suffit pour tester la recherche.
    """

    DIMENSIONS = 64

    def __init__(self) -> None:
        pass

    def __call__(self, input: Documents) -> Embeddings:
        vectors = []
        for text in input:
            vector = np.zeros(self.DIMENSIONS, dtype=np.float32)
            for word in re.findall(r"\w+", text.lower()):
                vector[zlib.crc32(word.encode()) % self.DIMENSIONS] += 1.0
            # Vecteur unitaire : la distance dépend des mots communs, pas de la longueur du texte
            norm = np.linalg.norm(vector)
            vectors.append(vector / norm if norm else vector)
        return vectors

    @staticmethod
    def name() -> str:
        return "fake-bag-of-words"

    def get_config(self) -> dict[str, Any]:
        return {}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "FakeEmbeddingFunction":
        return FakeEmbeddingFunction()


class FakeLLMClient:
    """Faux LLM : renvoie les réponses prévues, dans l'ordre, et garde la trace des appels.

    Une réponse de type LLMError est levée au lieu d'être renvoyée.
    """

    def __init__(self) -> None:
        self.json_answers: list[str | LLMError] = []
        self.json_calls: list[dict[str, object]] = []
        self.tool_answers: list[Message | LLMError] = []
        # Taille des morceaux de texte envoyés en streaming (0 : tout le texte d'un coup)
        self.chunk_size = 0
        self.tool_calls: list[dict[str, object]] = []

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

    async def stream_with_tools(
        self,
        messages: Sequence[Message],
        *,
        system: str,
        tools: Sequence[ToolDefinition],
        temperature: float,
    ) -> AsyncIterator[str | Message]:
        """Envoie le texte de la réponse prévue par morceaux de chunk_size caractères, puis le Message complet."""
        # Copie de l'historique : l'agent continue de le compléter après l'appel
        self.tool_calls.append(
            {"messages": list(messages), "system": system, "tools": list(tools), "temperature": temperature}
        )
        answer = self.tool_answers.pop(0)
        if isinstance(answer, LLMError):
            raise answer
        size = self.chunk_size or len(answer.content) or 1
        for start in range(0, len(answer.content), size):
            yield answer.content[start : start + size]
        yield answer

    async def aclose(self) -> None:
        pass


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


def parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    """Renvoie les événements (nom, données) d'un flux SSE, sans les commentaires de maintien."""
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        if fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events
