from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.core.settings import Settings
from app.schemas.debate import SpecterBrief

logger = logging.getLogger(__name__)


_RED_FLAG_HIGHLIGHTS = {
    "no_recent_funding",
    "headcount_decline",
    "negative_news",
    "lawsuit",
    "shutdown",
    "fraud",
}


class SpecterClient:
    """Thin async wrapper around the Specter REST API.

    Failure modes are intentionally swallowed so the debate can continue with
    a "vendor intelligence unavailable" brief.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._headers = {
            "X-API-Key": settings.specter_api_key,
            "Accept": "application/json",
        }
        self._timeout = httpx.Timeout(settings.specter_timeout_seconds)

    async def _search(self, client: httpx.AsyncClient, vendor: str) -> List[Dict[str, Any]]:
        url = f"{self._settings.specter_base_url}/companies/search"
        resp = await client.get(url, params={"query": vendor}, headers=self._headers)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return []

    async def _get_company(
        self, client: httpx.AsyncClient, company_id: str
    ) -> Optional[Dict[str, Any]]:
        url = f"{self._settings.specter_base_url}/companies/{company_id}"
        resp = await client.get(url, headers=self._headers)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return data
        return None

    async def lookup_vendor(self, vendor: str) -> SpecterBrief:
        if not self._settings.specter_api_key:
            return _unavailable_brief("Specter API key not configured")

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                results = await self._search(client, vendor)
                if not results:
                    return SpecterBrief(
                        status="available",
                        summary=f"No record of vendor '{vendor}' found in Specter.",
                        vendor_found=False,
                    )
                top = results[0]
                company_id = top.get("id") or top.get("company_id")
                detailed: Optional[Dict[str, Any]] = None
                if company_id:
                    try:
                        detailed = await self._get_company(client, company_id)
                    except httpx.HTTPError as exc:
                        logger.warning("Specter detail fetch failed: %s", exc)
                        detailed = None
                return _format_brief(top, detailed)
        except httpx.HTTPError as exc:
            logger.warning("Specter lookup failed: %s", exc)
            return _unavailable_brief(f"Specter request failed: {exc}")
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected Specter failure")
            return _unavailable_brief(f"Specter unexpected error: {exc}")


def _unavailable_brief(reason: str) -> SpecterBrief:
    return SpecterBrief(
        status="unavailable",
        summary=f"Vendor intelligence unavailable from Specter ({reason}).",
        vendor_found=False,
    )


def _format_brief(
    basic: Dict[str, Any], detailed: Optional[Dict[str, Any]]
) -> SpecterBrief:
    src = detailed or basic
    name = src.get("name") or basic.get("name") or "Unknown"
    domain = src.get("domain") or basic.get("domain")
    founded_year = src.get("founded_year") or basic.get("founded_year")
    description = src.get("description") or src.get("tagline") or basic.get("tagline")
    highlights = src.get("highlights") or []
    if not isinstance(highlights, list):
        highlights = []
    red_flags = [str(h) for h in highlights if str(h) in _RED_FLAG_HIGHLIGHTS]

    legitimacy_score = _derive_legitimacy_score(src)

    parts = [f"Vendor: {name}"]
    if domain:
        parts.append(f"Domain: {domain}")
    if founded_year:
        parts.append(f"Founded: {founded_year}")
    if legitimacy_score is not None:
        parts.append(f"Legitimacy score: {legitimacy_score:.2f}")
    if description:
        parts.append(f"Description: {description}")
    if red_flags:
        parts.append(f"Red flags: {', '.join(red_flags)}")
    elif highlights:
        sample = ", ".join(str(h) for h in highlights[:3])
        parts.append(f"Highlights: {sample}")

    summary = ". ".join(parts)

    return SpecterBrief(
        status="available",
        summary=summary,
        vendor_found=True,
        vendor_name=name,
        domain=domain,
        founded_year=int(founded_year) if isinstance(founded_year, (int, float)) else None,
        legitimacy_score=legitimacy_score,
        red_flags=red_flags,
        raw={"basic": basic, "detailed": detailed},
    )


def _derive_legitimacy_score(src: Dict[str, Any]) -> Optional[float]:
    """Best-effort numeric legitimacy score in 0..1 range.

    Specter does not publish a single legitimacy field, so we approximate
    using the company status, founded year, and domain presence.
    """
    score = 0.5
    if src.get("domain"):
        score += 0.15
    status = (src.get("status") or "").lower()
    if status in {"active", "operating"}:
        score += 0.15
    elif status in {"closed", "shutdown", "inactive"}:
        score -= 0.3
    fy = src.get("founded_year")
    if isinstance(fy, (int, float)) and fy > 0:
        if fy <= 2015:
            score += 0.15
        elif fy <= 2020:
            score += 0.05
    score = max(0.0, min(1.0, score))
    return round(score, 2)
