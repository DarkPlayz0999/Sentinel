"""AI explanations: plain-language summaries and grounded questions.

    GET  /v1/ai/status      is the AI configured, which model, does data leave the machine
    POST /v1/ai/summary     summary of one page: overview | lot | part | simulation |
                            experiment | workflow
    POST /v1/ai/ask         a question about that page, answered from its facts only

Every response says where the text came from (`source`: mistral or built-in),
whether the number check passed, and carries the exact facts it was built on.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.app.ai import llm, narrator
from backend.app.core.exceptions import ConflictError
from backend.app.schemas.common import ERROR_RESPONSES

router = APIRouter(prefix="/v1/ai", tags=["ai"], responses=ERROR_RESPONSES)

Context = Literal["overview", "lot", "part", "simulation", "experiment", "workflow", "realdata"]


class Subject(BaseModel):
    context: Context = "overview"
    id: str | None = Field(None, description="simulation, experiment or workflow id")
    serial: str | None = Field(None, description="a part or board serial")
    lot: str | None = None


class SummaryIn(Subject):
    refresh: bool = Field(False, description="Bypass the cache and write a new one")


class AskIn(Subject):
    question: str = Field(..., min_length=1, max_length=500)


def _ids(b: Subject) -> dict:
    ids = {"id": b.id, "serial": b.serial, "lot": b.lot}
    if b.context == "part" and not b.serial:
        raise ConflictError("context 'part' needs a serial.")
    if b.context == "lot" and not b.lot:
        raise ConflictError("context 'lot' needs a lot.")
    if b.context == "simulation" and not b.id:
        raise ConflictError("context 'simulation' needs an id.")
    return ids


@router.get("/status", summary="AI configuration (never the key itself)")
async def status():
    return llm.config().public()


@router.post("/summary", summary="Plain-language summary of one page, number-checked")
def summary(body: SummaryIn):
    return narrator.summarize(body.context, refresh=body.refresh, **_ids(body))


@router.post("/ask", summary="Answer a question from that page's facts only")
def ask(body: AskIn):
    return narrator.ask(body.context, body.question, **_ids(body))
