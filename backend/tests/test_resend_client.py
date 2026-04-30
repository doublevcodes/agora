from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.settings import Settings
from app.integrations.resend_client import ResendClient


def _settings(**overrides: str) -> Settings:
    base = {
        "OPENROUTER_API_KEY": "x",
        "RESEND_API_KEY": "",
        "RESEND_FROM_EMAIL": "onboarding@resend.dev",
        "RESEND_TO_EMAIL": "",
    }
    base.update(overrides)
    return Settings(**base)


@pytest.mark.asyncio
async def test_send_escalation_email_skips_when_not_configured() -> None:
    client = ResendClient(_settings())

    with patch("app.integrations.resend_client.httpx.AsyncClient") as async_client_cls:
        await client.send_escalation_email(
            trace_id="trace-123",
            escalation_packet={"transaction": {"vendor": "ACME"}},
        )
        async_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_send_escalation_email_posts_when_configured() -> None:
    client = ResendClient(
        _settings(
            RESEND_API_KEY="re_123",
            RESEND_FROM_EMAIL="alerts@example.com",
            RESEND_TO_EMAIL="ops@example.com",
        )
    )

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=mock_response)
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_http_client
    mock_cm.__aexit__.return_value = None

    with patch(
        "app.integrations.resend_client.httpx.AsyncClient",
        return_value=mock_cm,
    ):
        await client.send_escalation_email(
            trace_id="trace-123",
            escalation_packet={
                "transaction": {"vendor": "ACME", "amount": 42, "currency": "GBP"},
                "rationale": "Needs review.",
            },
        )

    mock_http_client.post.assert_awaited_once()
    _, kwargs = mock_http_client.post.await_args
    payload = kwargs["json"]
    assert payload["subject"] == "[Agora] Human escalation required (trace-12)"
    assert "Escalation packet:" in payload["text"]
    assert '"vendor": "ACME"' in payload["text"]
    assert "<h2" in payload["html"]
    assert "Human escalation required" in payload["html"]
    assert "&quot;vendor&quot;: &quot;ACME&quot;" in payload["html"]


@pytest.mark.asyncio
async def test_send_escalation_email_swallows_http_error() -> None:
    client = ResendClient(
        _settings(
            RESEND_API_KEY="re_123",
            RESEND_FROM_EMAIL="alerts@example.com",
            RESEND_TO_EMAIL="ops@example.com",
        )
    )

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(side_effect=httpx.HTTPError("boom"))
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_http_client
    mock_cm.__aexit__.return_value = None

    with patch(
        "app.integrations.resend_client.httpx.AsyncClient",
        return_value=mock_cm,
    ):
        await client.send_escalation_email(
            trace_id="trace-123",
            escalation_packet={"transaction": {"vendor": "ACME"}},
        )
