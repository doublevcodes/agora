from __future__ import annotations

import html
import logging
import json
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
        packet_pretty = json.dumps(escalation_packet, indent=2, default=str)
        trace_id_safe = html.escape(trace_id)
        vendor_safe = html.escape(str(vendor))
        amount_line_safe = html.escape(amount_line)
        rationale_safe = html.escape(str(rationale))
        packet_pretty_safe = html.escape(packet_pretty)
        html_body = (
            "<div style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', "
            "Roboto, Helvetica, Arial, sans-serif; line-height: 1.5; color: #111827;\">"
            "<h2 style=\"margin: 0 0 12px; color: #111827;\">Human escalation required</h2>"
            "<p style=\"margin: 0 0 16px; color: #374151;\">"
            "Agora escalated a transaction for human review."
            "</p>"
            "<table style=\"border-collapse: collapse; margin-bottom: 16px;\">"
            "<tr><td style=\"padding: 4px 12px 4px 0; color: #6B7280;\"><strong>Trace ID</strong></td>"
            f"<td style=\"padding: 4px 0;\">{trace_id_safe}</td></tr>"
            "<tr><td style=\"padding: 4px 12px 4px 0; color: #6B7280;\"><strong>Vendor</strong></td>"
            f"<td style=\"padding: 4px 0;\">{vendor_safe}</td></tr>"
            "<tr><td style=\"padding: 4px 12px 4px 0; color: #6B7280;\"><strong>Amount</strong></td>"
            f"<td style=\"padding: 4px 0;\">{amount_line_safe}</td></tr>"
            "<tr><td style=\"padding: 4px 12px 4px 0; color: #6B7280;\"><strong>Reason</strong></td>"
            f"<td style=\"padding: 4px 0;\">{rationale_safe}</td></tr>"
            "</table>"
            "<h3 style=\"margin: 0 0 8px; font-size: 14px; color: #111827;\">Escalation packet</h3>"
            "<pre style=\"margin: 0; padding: 12px; background: #F9FAFB; border: 1px solid #E5E7EB; "
            "border-radius: 6px; overflow: auto; font-size: 12px; line-height: 1.4;\">"
            f"{packet_pretty_safe}"
            "</pre>"
            "</div>"
        )

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
                f"{packet_pretty}"
            ),
            "html": html_body,
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
