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
_QUARTER_TOKEN_RE = re.compile(r"^Q[1-4](?:[-_/][A-Z0-9]+)?$", re.IGNORECASE)


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


def _split_vendor_and_notes(vendor_candidate: str) -> tuple[str, Optional[str]]:
    """Split cleaned text into vendor + optional notes.

    Heuristics:
    - vendor is usually an uppercase company span
    - quarter/version tokens such as Q1/Q2 often start notes
    - once narrative lowercase text starts, remaining text is treated as notes
    """
    tokens = vendor_candidate.split()
    if not tokens:
        return "UNKNOWN VENDOR", None

    vendor_tokens: list[str] = []
    note_tokens: list[str] = []

    for idx, tok in enumerate(tokens):
        tok_is_quarter = bool(_QUARTER_TOKEN_RE.match(tok))
        tok_is_upper = tok.isupper() and any(ch.isalpha() for ch in tok)
        tok_has_lower = any(ch.islower() for ch in tok)

        # Treat quarter/version marker as note boundary once a plausible vendor exists.
        if tok_is_quarter and len(vendor_tokens) >= 2:
            note_tokens = tokens[idx:]
            break

        # Lowercase narrative token usually starts memo/description text.
        if tok_has_lower and len(vendor_tokens) >= 1:
            note_tokens = tokens[idx:]
            break

        if tok_is_upper or not vendor_tokens:
            vendor_tokens.append(tok)
            continue

        # Fallback boundary for non-uppercase token after vendor span.
        note_tokens = tokens[idx:]
        break

    if not vendor_tokens:
        vendor_tokens = tokens[:1]
        note_tokens = tokens[1:]

    vendor = " ".join(vendor_tokens).strip() or "UNKNOWN VENDOR"
    notes = " ".join(note_tokens).strip() or None
    return vendor, notes


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
        vendor, notes = _split_vendor_and_notes(vendor_candidate)
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
