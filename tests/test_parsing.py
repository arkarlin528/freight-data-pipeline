from datetime import date
from decimal import Decimal

import pytest

from freight_pipeline.reference import container_type, port_code
from freight_pipeline.transform.parsing import (
    cents_to_amount,
    parse_date,
    parse_date_range,
    parse_decimal_comma,
    parse_money,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("USD 1,250.00", ("USD", Decimal("1250.00"))),
        ("1,250.5 usd", ("USD", Decimal("1250.50"))),
        ("EUR 980", ("EUR", Decimal("980.00"))),
    ],
)
def test_money(text: str, expected: tuple[str, Decimal]) -> None:
    assert parse_money(text) == expected


@pytest.mark.parametrize("text", ["On request", "Call us", "TBA", "N/A"])
def test_on_request_is_not_a_price(text: str) -> None:
    with pytest.raises(ValueError, match="no price published"):
        parse_money(text)


@pytest.mark.parametrize("text", ["1,250.00", "USD", "USD 12a"])
def test_garbage_money_is_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_money(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-10-01", date(2026, 10, 1)),
        ("01 Oct 2026", date(2026, 10, 1)),
        ("1 October 2026", date(2026, 10, 1)),
        ("01/10/2026", date(2026, 10, 1)),  # day first, as the CSV source uses
    ],
)
def test_dates(text: str, expected: date) -> None:
    assert parse_date(text) == expected


def test_date_range_with_en_dash() -> None:
    assert parse_date_range("01 Oct 2026 – 31 Oct 2026") == (date(2026, 10, 1), date(2026, 10, 31))


def test_bad_date_is_rejected() -> None:
    with pytest.raises(ValueError, match="unrecognised date"):
        parse_date("31/31/2026")


def test_decimal_comma_and_cents() -> None:
    assert parse_decimal_comma("1.234,50") == Decimal("1234.50")
    assert parse_decimal_comma("245,00") == Decimal("245.00")
    assert cents_to_amount(123456) == Decimal("1234.56")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Laem Chabang, Thailand", "THLCH"),
        ("Ho Chi Minh City, Vietnam", "VNSGN"),
        ("Saigon", "VNSGN"),
        ("sgsin", "SGSIN"),
        ("Kuala Tanjung, Indonesia", None),
        ("XXXXX", None),
    ],
)
def test_port_codes(text: str, expected: str | None) -> None:
    assert port_code(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("20' Standard", "20GP"),
        ("40' Standard", "40GP"),
        ("40' High Cube", "40HC"),
        ("40'HC", "40HC"),
        ("40hq", "40HC"),
        ("20GP", "20GP"),
        ("45'HC", None),
        ("Reefer", None),
    ],
)
def test_container_types(text: str, expected: str | None) -> None:
    assert container_type(text) == expected
