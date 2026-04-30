from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.debate import router as debate_router
from app.core.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Agora",
        version="0.1.0",
        description=(
            "Two-agent adversarial payment authorisation system. "
            "Hermes argues for, Nemesis argues against, Verdict decides."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(debate_router)

    @app.get("/")
    async def root() -> dict:
        return {"name": "agora", "status": "ready"}

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return app


app = create_app()
