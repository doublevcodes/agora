from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.core.settings import Settings, get_settings
from app.schemas.debate import DebateRequest
from app.services.debate_orchestrator import DebateOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter()


def _orchestrator(settings: Settings = Depends(get_settings)) -> DebateOrchestrator:
    return DebateOrchestrator(settings)


async def _sse_stream(
    request: Request,
    orchestrator: DebateOrchestrator,
    payload: DebateRequest,
) -> AsyncIterator[bytes]:
    try:
        async for envelope in orchestrator.run(
            raw_transaction=payload.raw_transaction,
            max_rounds=payload.max_rounds,
            escalation_email=payload.escalation_email,
        ):
            if await request.is_disconnected():
                logger.info("Client disconnected; stopping debate stream early")
                return
            data = envelope.model_dump_json()
            line = f"event: {envelope.event_type}\ndata: {data}\n\n"
            yield line.encode("utf-8")
    except Exception as exc:  # pragma: no cover - safety net
        logger.exception("Debate stream crashed")
        err = json.dumps({"event_type": "error", "payload": {"message": str(exc)}})
        yield f"event: error\ndata: {err}\n\n".encode("utf-8")


@router.post("/debate")
async def debate(
    payload: DebateRequest,
    request: Request,
    orchestrator: DebateOrchestrator = Depends(_orchestrator),
) -> StreamingResponse:
    return StreamingResponse(
        _sse_stream(request, orchestrator, payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
