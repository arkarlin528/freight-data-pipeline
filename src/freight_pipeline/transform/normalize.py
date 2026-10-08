"""
Raw records → validated Rates. Each source has its own mapping (formats differ wildly); the
validation rules after that are shared (see models.Rate). Every record ends up either as a Rate
or as a Rejection with a reason. Nothing is dropped silently, except exact duplicates (counted).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from pydantic import ValidationError

from freight_pipeline.models import Rate, RawRecord, Rejection, TransformResult
from freight_pipeline.reference import container_type, port_code
from freight_pipeline.transform.parsing import (
    cents_to_amount,
    parse_date,
    parse_date_range,
    parse_decimal_comma,
    parse_money,
)


def _require_port(text: str, role: str) -> str:
    code = port_code(text)
    if code is None:
        raise ValueError(f"unknown {role} port '{text}'")
    return code


def _require_container(text: str) -> str:
    code = container_type(text)
    if code is None:
        raise ValueError(f"unsupported container type '{text}'")
    return code


def _asl(f: dict[str, str]) -> dict[str, Any]:
    currency, amount = parse_money(f["rate"])
    valid_from, valid_to = parse_date_range(f["validity"])
    return {
        "carrier": "ASL",
        "origin": _require_port(f["from"], "origin"),
        "destination": _require_port(f["to"], "destination"),
        "container_type": _require_container(f["equipment"]),
        "currency": currency,
        "amount": amount,
        "valid_from": valid_from,
        "valid_to": valid_to,
    }


def _mcl(f: dict[str, str]) -> dict[str, Any]:
    return {
        "carrier": "MCL",
        "origin": _require_port(f["pol"], "origin"),
        "destination": _require_port(f["pod"], "destination"),
        "container_type": _require_container(f["eqp"]),
        "currency": f["ccy"].strip().upper(),
        "amount": cents_to_amount(f["price_cents"]),
        "valid_from": parse_date(f["effective"]),
        "valid_to": parse_date(f["expiry"]),
    }


def _ssc(f: dict[str, str]) -> dict[str, Any]:
    return {
        "carrier": "SSC",
        "origin": _require_port(f["origin_code"], "origin"),
        "destination": _require_port(f["destination_code"], "destination"),
        "container_type": _require_container(f["container"]),
        "currency": f["currency"].strip().upper(),
        "amount": parse_decimal_comma(f["amount"]),
        "valid_from": parse_date(f["valid_from"]),
        "valid_to": parse_date(f["valid_to"]),
    }


MAPPERS: dict[str, Callable[[dict[str, str]], dict[str, Any]]] = {"asl": _asl, "mcl": _mcl, "ssc": _ssc}


def transform(records: Iterable[RawRecord]) -> TransformResult:
    result = TransformResult()
    seen: dict[tuple[Any, ...], Rate] = {}

    for record in records:
        try:
            candidate = MAPPERS[record.source](record.fields)
            rate = Rate(**candidate, source_ref=record.ref)
        except (ValueError, KeyError) as exc:
            result.rejections.append(Rejection(record.source, record.ref, _reason(exc), record.fields))
            continue

        previous = seen.get(rate.key)
        if previous is None:
            seen[rate.key] = rate
            result.rates.append(rate)
        elif (previous.amount, previous.currency, previous.valid_to) == (rate.amount, rate.currency, rate.valid_to):
            result.duplicates += 1  # the same row twice (e.g. repeated across pages): harmless
        else:
            result.rejections.append(
                Rejection(
                    record.source,
                    record.ref,
                    f"conflicts with {previous.source_ref} ({previous.currency} {previous.amount})",
                    record.fields,
                )
            )

    return result


def _reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        error = exc.errors()[0]
        location = ".".join(str(part) for part in error["loc"])
        message = str(error["msg"]).removeprefix("Value error, ")
        return f"{location}: {message}" if location else message
    if isinstance(exc, KeyError):
        return f"missing field {exc}"
    return str(exc)
