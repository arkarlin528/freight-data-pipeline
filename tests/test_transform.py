from decimal import Decimal

import httpx

from freight_pipeline.extract.sources import AslHtmlSource, MclSource, SscCsvSource
from freight_pipeline.models import RawRecord
from freight_pipeline.transform.normalize import transform


def _ssc(**overrides: str) -> RawRecord:
    fields = {
        "origin_code": "THLCH",
        "destination_code": "SGSIN",
        "container": "40HC",
        "amount": "1234,50",
        "currency": "usd",
        "valid_from": "01/10/2026",
        "valid_to": "31/10/2026",
    }
    return RawRecord("ssc", "ssc/rates.csv#line-2", {**fields, **overrides})


def test_valid_row_becomes_a_rate() -> None:
    result = transform([_ssc()])

    assert not result.rejections
    rate = result.rates[0]
    assert (rate.carrier, rate.origin, rate.destination, rate.container_type) == ("SSC", "THLCH", "SGSIN", "40HC")
    assert (rate.currency, rate.amount) == ("USD", Decimal("1234.50"))


def test_every_problem_is_rejected_with_a_reason() -> None:
    result = transform(
        [
            _ssc(destination_code="XXXXX"),
            _ssc(destination_code="THLCH"),
            _ssc(container="45HC"),
            _ssc(amount="0,00"),
            _ssc(valid_from="31/10/2026", valid_to="01/10/2026"),
            _ssc(valid_from="someday"),
            RawRecord("ssc", "ssc/rates.csv#line-9", {"origin_code": "THLCH"}),
        ]
    )

    reasons = [r.reason for r in result.rejections]
    assert not result.rates
    assert reasons == [
        "unknown destination port 'XXXXX'",
        "origin and destination are the same port",
        "unsupported container type '45HC'",
        "amount: Input should be greater than 0",
        "valid_to is before valid_from",
        "unrecognised date 'someday'",
        "missing field 'destination_code'",
    ]


def test_exact_duplicates_are_dropped_and_conflicts_rejected() -> None:
    result = transform([_ssc(), _ssc(), _ssc(amount="999,00")])

    assert len(result.rates) == 1
    assert result.duplicates == 1
    assert result.rejections[0].reason.startswith("conflicts with ssc/rates.csv#line-2")


def test_parsers_read_the_real_mock_pages(mock_site: httpx.Client) -> None:
    asl, mcl, ssc = AslHtmlSource(""), MclSource(""), SscCsvSource("")

    asl_rows = asl.parse("asl/page-1.html", mock_site.get("/asl/tariffs?page=1").content)
    mcl_rows = mcl.parse("mcl/rates.json", mock_site.get("/mcl/api/rates").content)
    ssc_rows = ssc.parse("ssc/rates.csv", mock_site.get("/ssc/rates.csv").content)

    assert len(asl_rows) == 25
    assert asl_rows[0].fields["from"] == "Laem Chabang, Thailand"
    assert asl_rows[0].fields["rate"].startswith("USD ")
    assert len(mcl_rows) == 100 and mcl_rows[0].fields["eqp"] == "20'GP"
    assert len(ssc_rows) == 101 and ssc_rows[0].ref == "ssc/rates.csv#line-2"


def test_layout_change_is_noticed(caplog: object) -> None:
    rows = AslHtmlSource("").parse("asl/page-1.html", b"<html><body><p>We moved!</p></body></html>")

    assert rows == []
