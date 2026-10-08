from freight_pipeline.models import Rejection
from freight_pipeline.report import RunSummary, _rejection_table, render


def test_rejections_group_by_problem_not_by_value() -> None:
    table = _rejection_table(
        [
            Rejection("asl", "asl/page-1.html#row-6", "no price published ('On request')", {}),
            Rejection("asl", "asl/page-2.html#row-3", "no price published ('Call us')", {}),
            Rejection("mcl", "mcl/rates.json#item-100", "unsupported container type '45'HC'", {}),
        ]
    )

    assert "| `asl` | no price published | 2 |" in table[2]
    assert "| `mcl` | unsupported container type | 1 |" in table[3]


def test_failed_run_report_shows_the_error() -> None:
    text = render(RunSummary(run_id="abc", status="failed", error="RetryableHttpError: 503"))

    assert "❌ failed" in text
    assert "RetryableHttpError: 503" in text
