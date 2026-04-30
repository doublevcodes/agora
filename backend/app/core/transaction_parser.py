from __future__ import annotations

import re
from typing import Optional

from app.schemas.debate import ParsedTransaction


_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}(?:/\d{2,4})?|\d{4}-\d{2}-\d{2})\b")
_AMOUNT_RE = re.compile(
    r"(?P<amount>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?P<currency>GBP|USD|EUR|CAD|AUD|CHF|JPY|\$|£|€)?",
    re.IGNORECASE,
)
_REF_RE = re.compile(r"REF[:\s#-]*([A-Z0-9][A-Z0-9\-_/]*)", re.IGNORECASE)

_CURRENCY_SYMBOL_MAP = {"$": "USD", "£": "GBP", "€": "EUR"}

_NOISE_TOKENS = {"REF", "REFERENCE", "INV", "INVOICE", "PAYMENT", "PAYEE"}


def _clean_vendor(text: str) -> str:
    tokens = [t for t in re.split(r"\s+", text.strip()) if t]
    cleaned: list[str] = []
    for tok in tokens:
        if tok.upper() in _NOISE_TOKENS:
            continue
        cleaned.append(tok)
    out = " ".join(cleaned).strip(" -:,")
    return re.sub(r"\s{2,}", " ", out)


def _normalize_amount(raw: str) -> Optional[float]:
    if not raw:
        return None
    cleaned = raw.replace(",", "").replace(" ", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_transaction(raw_text: str) -> ParsedTransaction:
    """Best-effort parser for free-form bank statement lines.

    The parser is intentionally lenient: missing fields remain ``None`` while a
    vendor name is always attempted so that downstream Specter lookups have
    something to work with.
    """
    raw = raw_text.strip()
    if not raw:
        raise ValueError("raw transaction text is empty")

    working = raw

    date_match = _DATE_RE.search(working)
    date_value = date_match.group(1) if date_match else None
    if date_match:
        working = working.replace(date_match.group(0), " ", 1)

    ref_match = _REF_RE.search(working)
    reference = ref_match.group(1) if ref_match else None
    if ref_match:
        working = working.replace(ref_match.group(0), " ", 1)

    amount_value: Optional[float] = None
    currency_value: Optional[str] = None
    amount_span: Optional[tuple[int, int]] = None
    for m in _AMOUNT_RE.finditer(working):
        amt = _normalize_amount(m.group("amount"))
        if amt is None or amt < 1:
            continue
        amount_value = amt
        cur = m.group("currency")
        if cur:
            cur_norm = _CURRENCY_SYMBOL_MAP.get(cur, cur.upper())
            currency_value = cur_norm
        amount_span = m.span()
        break

    if amount_span is not None:
        working = working[: amount_span[0]] + " " + working[amount_span[1] :]

    if currency_value is None:
        cur_match = re.search(r"\b(GBP|USD|EUR|CAD|AUD|CHF|JPY)\b", working, re.IGNORECASE)
        if cur_match:
            currency_value = cur_match.group(1).upper()
            working = working.replace(cur_match.group(0), " ", 1)

    vendor_candidate = _clean_vendor(working)
    notes: Optional[str] = None
    if vendor_candidate:
        parts = [p for p in re.split(r"\s{2,}|\s-\s", vendor_candidate) if p.strip()]
        if len(parts) > 1:
            vendor = parts[0].strip()
            notes = " ".join(parts[1:]).strip() or None
        else:
            tokens = vendor_candidate.split()
            cap_tokens: list[str] = []
            tail_tokens: list[str] = []
            seen_lower = False
            for tok in tokens:
                if not seen_lower and (tok.isupper() or tok[:1].isupper() and tok.upper() == tok):
                    cap_tokens.append(tok)
                else:
                    seen_lower = True
                    tail_tokens.append(tok)
            if cap_tokens and tail_tokens:
                vendor = " ".join(cap_tokens).strip()
                notes = " ".join(tail_tokens).strip() or None
            else:
                vendor = vendor_candidate
    else:
        vendor = "UNKNOWN VENDOR"

    return ParsedTransaction(
        raw=raw,
        date=date_value,
        vendor=vendor or "UNKNOWN VENDOR",
        amount=amount_value,
        currency=currency_value,
        reference=reference,
        notes=notes,
    )
