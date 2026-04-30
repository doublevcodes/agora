from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    specter_api_key: str = Field(default="", alias="SPECTER_API_KEY")

    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        alias="OPENROUTER_BASE_URL",
    )
    openrouter_referer: str = Field(
        default="https://agora.local",
        alias="OPENROUTER_REFERER",
    )
    openrouter_app_title: str = Field(
        default="Agora",
        alias="OPENROUTER_APP_TITLE",
    )

    specter_base_url: str = Field(
        default="https://app.tryspecter.com/api/v1",
        alias="SPECTER_BASE_URL",
    )
    specter_timeout_seconds: float = Field(default=8.0, alias="SPECTER_TIMEOUT_SECONDS")
    resend_api_key: str = Field(default="", alias="RESEND_API_KEY")
    resend_base_url: str = Field(
        default="https://api.resend.com",
        alias="RESEND_BASE_URL",
    )
    resend_from_email: str = Field(
        default="onboarding@resend.dev",
        alias="RESEND_FROM_EMAIL",
    )
    resend_to_email: str = Field(default="", alias="RESEND_TO_EMAIL")

    model_low_risk: str = Field(
        default="openai/gpt-4o-mini",
        alias="MODEL_LOW_RISK",
    )
    model_medium_risk: str = Field(
        default="openai/gpt-4o",
        alias="MODEL_MEDIUM_RISK",
    )
    model_high_risk: str = Field(
        default="anthropic/claude-3.5-sonnet",
        alias="MODEL_HIGH_RISK",
    )
    model_verdict_default: str = Field(
        default="anthropic/claude-3.5-sonnet",
        alias="MODEL_VERDICT_DEFAULT",
    )
    model_verdict_high_risk: str = Field(
        default="anthropic/claude-3.5-sonnet",
        alias="MODEL_VERDICT_HIGH_RISK",
    )

    risk_amount_medium_threshold: float = Field(
        default=5_000.0, alias="RISK_AMOUNT_MEDIUM_THRESHOLD"
    )
    risk_amount_high_threshold: float = Field(
        default=20_000.0, alias="RISK_AMOUNT_HIGH_THRESHOLD"
    )

    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="CORS_ORIGINS",
    )

    debate_max_rounds: int = Field(default=6, alias="DEBATE_MAX_ROUNDS")
    structured_retry_attempts: int = Field(
        default=2, alias="STRUCTURED_RETRY_ATTEMPTS"
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
