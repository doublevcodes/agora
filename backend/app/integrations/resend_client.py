from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from app.core.settings import Settings

logger = logging.getLogger(__name__)


class ResendClient:
    """Minimal async wrapper around the Resend email API."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._timeout = httpx.Timeout(8.0)

    @property
    def is_configured(self) -> bool:
        return bool(
            self._settings.resend_api_key
            and self._settings.resend_from_email
        )

    async def send_escalation_email(
        self,
        *,
        trace_id: str,
        escalation_packet: Dict[str, Any],
        delivery_email: str | None = None,
    ) -> None:
        recipient = (delivery_email or "").strip() or self._settings.resend_to_email
        if not self.is_configured or not recipient:
            logger.info(
                "Skipping escalation email: Resend is not fully configured "
                "(RESEND_API_KEY/RESEND_FROM_EMAIL plus a recipient email)"
            )
            return

        tx = escalation_packet.get("transaction") or {}
        vendor = tx.get("vendor") or "Unknown vendor"
        amount = tx.get("amount")
        currency = tx.get("currency") or ""
        amount_line = (
            f"{amount} {currency}".strip()
            if amount is not None
            else "unknown amount"
        )
        rationale = escalation_packet.get("rationale") or "No rationale provided."

        payload = {
            "from": self._settings.resend_from_email,
            "to": [recipient],
            "subject": f"[Agora] Human escalation required ({trace_id[:8]})",
            "text": (
                "Agora escalated a transaction for human review.\n\n"
                f"Trace ID: {trace_id}\n"
                f"Vendor: {vendor}\n"
                f"Amount: {amount_line}\n"
                f"Reason: {rationale}\n\n"
                "Escalation packet:\n"
                f"{escalation_packet}"
            ),
        }
        headers = {
            "Authorization": f"Bearer {self._settings.resend_api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._settings.resend_base_url.rstrip('/')}/emails"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Failed to send Resend escalation email: %s", exc)
