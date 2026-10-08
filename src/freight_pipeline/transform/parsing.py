"""Small, strict parsers for the messy formats carriers publish. Each raises ValueError with a readable reason."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_DATE_FORMATS = ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d/%m/%Y")


def parse_date(text: str) -> date:
    cleaned = text.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date '{text}'")


def parse_date_range(text: str) -> tuple[date, date]:
    """'01 Oct 2026 – 31 Oct 2026' (en dash, hyphen or 'to')."""
    parts = re.split(r"\s+(?:–|—|-|to|→)\s+", text.strip())
    if len(parts) != 2:
        raise ValueError(f"unrecognised validity '{text}'")
    return parse_date(parts[0]), parse_date(parts[1])


def parse_money(text: str) -> tuple[str, Decimal]:
    """'USD 1,250.00' / '1,250.00 USD' → ('USD', Decimal('1250.00')). 'On request' is not a price."""
    cleaned = text.strip()
    if re.search(r"request|call|n/?a|tba", cleaned, re.IGNORECASE):
        raise ValueError(f"no price published ('{cleaned}')")
    match = re.fullmatch(r"(?:([A-Za-z]{3})\s*)?([\d.,]+)(?:\s*([A-Za-z]{3}))?", cleaned)
    if not match or not (match.group(1) or match.group(3)):
        raise ValueError(f"unrecognised price '{text}'")
    currency = (match.group(1) or match.group(3)).upper()
    return currency, _decimal(match.group(2).replace(",", ""))


def parse_decimal_comma(text: str) -> Decimal:
    """European format: '1.234,50' or '1234,50' → Decimal('1234.50')."""
    return _decimal(text.strip().replace(".", "").replace(",", "."))


def cents_to_amount(cents: int | str) -> Decimal:
    return (Decimal(int(cents)) / 100).quantize(Decimal("0.01"))


def _decimal(text: str) -> Decimal:
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"unrecognised amount '{text}'") from exc
