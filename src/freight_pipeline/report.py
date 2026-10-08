"""Human-readable run report (Markdown): what came in, what was rejected and why, what moved."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from freight_pipeline.extract.http import FetchStats
from freight_pipeline.load.repository import LoadResult, PriceMove
from freight_pipeline.models import Rejection, TransformResult
from freight_pipeline.publish.logistics import PublishResult


@dataclass
class RunSummary:
    run_id: str
    status: str
    extracted_by_source: dict[str, int] = field(default_factory=dict)
    transform: TransformResult | None = None
    load: LoadResult | None = None
    publish: PublishResult | None = None
    fetch: FetchStats | None = None
    moves: list[PriceMove] = field(default_factory=list)
    error: str | None = None

    @property
    def extracted(self) -> int:
        return sum(self.extracted_by_source.values())


def render(summary: RunSummary) -> str:
    t, ld, pub, f = summary.transform, summary.load, summary.publish, summary.fetch
    lines = [
        f"# Freight rate run `{summary.run_id}`",
        "",
        f"- **Status:** {'✅' if summary.status == 'succeeded' else '❌'} {summary.status}",
        f"- **Finished:** {datetime.now(UTC):%Y-%m-%d %H:%M} UTC",
    ]
    if f:
        lines.append(
            f"- **HTTP:** {f.requests} requests, {f.retries} retries, {f.bytes / 1024:.0f} KiB, "
            f"status codes {dict(f.by_status)}"
        )
    if summary.error:
        lines += ["", f"> **Error:** {summary.error}"]

    lines += ["", "## Pipeline", "", "| Step | Count |", "|---|---:|"]
    for source, n in summary.extracted_by_source.items():
        lines.append(f"| Extracted from `{source}` | {n} |")
    if t:
        lines += [
            f"| Valid rates | {len(t.rates)} |",
            f"| Rejected | {len(t.rejections)} |",
            f"| Exact duplicates dropped | {t.duplicates} |",
        ]
    if ld:
        lines += [
            f"| Loaded: new | {ld.inserted} |",
            f"| Loaded: price changed | {ld.updated} |",
            f"| Loaded: unchanged | {ld.unchanged} |",
        ]
    if pub:
        lines += [f"| Published to logistics platform | {pub.sent} |", f"| Platform rejected | {len(pub.rejected)} |"]

    if t and t.rejections:
        lines += ["", "## Data quality: rejected rows", ""]
        lines += _rejection_table(t.rejections)

    if summary.moves:
        lines += [
            "",
            "## Biggest price moves",
            "",
            "| Carrier | Lane | Container | Before | Now | Change |",
            "|---|---|---|---:|---:|---:|",
        ]
        for m in summary.moves:
            lines.append(
                f"| {m.carrier} | {m.origin} → {m.destination} | {m.container_type} | {m.previous} | "
                f"{m.current} | {m.change_pct:+.1f}% |"
            )
    return "\n".join(lines) + "\n"


def _rejection_table(rejections: list[Rejection]) -> list[str]:
    def category(reason: str) -> str:
        # Drop the quoted values so rows with the same problem group together.
        # The quoted value always comes last, and may itself contain quotes (e.g. '45'HC').
        return re.sub(r"\s*\(?'.*'\)?\s*$", "", reason).strip() or reason

    grouped: dict[tuple[str, str], list[Rejection]] = defaultdict(list)
    for r in rejections:
        grouped[(r.source, category(r.reason))].append(r)
    counts = Counter({k: len(v) for k, v in grouped.items()})
    lines = ["| Source | Reason | Rows | Example |", "|---|---|---:|---|"]
    for (source, reason), n in counts.most_common():
        example = grouped[(source, reason)][0]
        lines.append(f"| `{source}` | {reason} | {n} | `{example.ref}`: {example.reason} |")
    return lines
