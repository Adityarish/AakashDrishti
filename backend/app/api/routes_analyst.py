"""AI analyst endpoints (FR-41..FR-45): status, findings, streamed report, Q&A."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.analyst import report as analyst
from app.analyst.pdf_report import build_brief_pdf
from app.api.deps import get_job_store
from app.auth.service import Principal, require_responder
from app.core.config import Settings, get_settings
from app.jobs.store import JobNotFoundError, JobStore

router = APIRouter(prefix="/api/analyst", tags=["analyst"])


def _dir(job_id: str, store: JobStore):
    try:
        store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return store.job_dir(job_id)


class FindingBody(BaseModel):
    tool: str
    title: str
    text: str
    data: dict[str, Any] = {}


class AskBody(BaseModel):
    question: str


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatBody(BaseModel):
    question: str
    history: list[ChatMessage] = []


class ReportBody(BaseModel):
    force_offline: bool = False


@router.get("/status")
def status(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "available": settings.analyst_available,
        "mode": "online" if settings.analyst_available else "offline_template",
        "model": settings.openai_model if settings.analyst_available else None,
        "note": (
            "Online analyst enabled: only derived statistics are sent, never imagery."
            if settings.analyst_available
            else "No OPENAI_API_KEY set: the offline template analyst writes reports from computed statistics."
        ),
    }


@router.get("/{job_id}/findings")
def list_findings(job_id: str, store: JobStore = Depends(get_job_store)) -> dict:
    return {"findings": analyst.load_findings(_dir(job_id, store))}


@router.post("/{job_id}/findings")
def add_finding(job_id: str, body: FindingBody, store: JobStore = Depends(get_job_store),
                principal: Principal = Depends(require_responder)) -> dict:
    directory = _dir(job_id, store)
    findings = analyst.load_findings(directory)
    item = {"id": uuid.uuid4().hex[:8], "created_at": time.time(), **body.model_dump()}
    findings.append(item)
    analyst.save_findings(directory, findings)
    return item


@router.delete("/{job_id}/findings")
def clear_findings(job_id: str, store: JobStore = Depends(get_job_store),
                   principal: Principal = Depends(require_responder)) -> dict:
    analyst.save_findings(_dir(job_id, store), [])
    return {"cleared": True}


@router.get("/{job_id}/report")
def cached_report(job_id: str, store: JobStore = Depends(get_job_store)) -> dict:
    cached = analyst.load_cached_report(_dir(job_id, store))
    return {"available": cached is not None, "report": cached}


@router.post("/{job_id}/report/stream")
async def stream_report(job_id: str, body: ReportBody, store: JobStore = Depends(get_job_store),
                        settings: Settings = Depends(get_settings),
                        principal: Principal = Depends(require_responder)) -> StreamingResponse:
    directory = _dir(job_id, store)

    async def events():
        iterator = analyst.report_events(settings, directory, body.force_offline)
        loop = asyncio.get_running_loop()
        sentinel = object()
        while True:
            item = await loop.run_in_executor(None, lambda: next(iterator, sentinel))
            if item is sentinel:
                break
            yield f"data: {json.dumps(item)}\n\n"
            if item["event"] == "text" and not settings.analyst_available:
                await asyncio.sleep(0.012)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/{job_id}/chat/stream")
async def stream_chat(job_id: str, body: ChatBody, store: JobStore = Depends(get_job_store),
                      settings: Settings = Depends(get_settings),
                      principal: Principal = Depends(require_responder)) -> StreamingResponse:
    """Multi-turn chat over this scene's statistics, streamed token by token (SSE).

    `history` carries the prior turns so follow-ups like "and at 2 m instead?" resolve; the scene
    statistics are re-read through the read-only tools on every turn, so answers always reflect
    the latest hazard runs. Raw imagery is never sent -- see app/analyst/tools.py.
    """
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Ask a question about the scene.")
    directory = _dir(job_id, store)
    history = [m.model_dump() for m in body.history]

    async def events():
        iterator = analyst.chat_events(settings, directory, question, history)
        loop = asyncio.get_running_loop()
        sentinel = object()
        while True:
            item = await loop.run_in_executor(None, lambda: next(iterator, sentinel))
            if item is sentinel:
                break
            yield f"data: {json.dumps(item)}\n\n"
            if item["event"] == "text" and not settings.analyst_available:
                await asyncio.sleep(0.012)  # pace the offline template so it reads as a live answer

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/{job_id}/ask")
async def ask(job_id: str, body: AskBody, store: JobStore = Depends(get_job_store),
              settings: Settings = Depends(get_settings), principal: Principal = Depends(require_responder)) -> dict:
    if not body.question.strip():
        raise HTTPException(status_code=422, detail="Ask a question about the scene.")
    directory = _dir(job_id, store)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: analyst.answer_question(settings, directory, body.question.strip()))


@router.get("/{job_id}/report.pdf")
def report_pdf(job_id: str, app_url: Optional[str] = Query(None, max_length=200), store: JobStore = Depends(get_job_store),
               settings: Settings = Depends(get_settings)):
    """Multi-page PDF: KPI cover, linked contents, the brief, charts, building/flood/landing/validation tables (PRD P2).

    `app_url` (the frontend origin) turns the "open in app" links on; without it the first CORS origin is used."""
    from fastapi.responses import Response

    directory = _dir(job_id, store)
    brief = analyst.load_cached_report(directory)
    if brief is None:  # no brief generated yet: ship the deterministic offline one rather than a 404
        context, _ = analyst.gather_context(directory)
        brief = {"text": analyst.template_report(context), "mode": "offline_template", "unverified_numbers": []}
    meta_path = directory / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    base = app_url if app_url and app_url.startswith(("http://", "https://")) else (settings.cors_origin_list or [None])[0]
    pdf = build_brief_pdf(job_id, directory, brief, meta, base)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="brief-{job_id[:8]}.pdf"'})
