"""Summarise a test batch from the per-row metrics (`Personalization.metrics`).

Pure functions over plain dicts, so the arithmetic is tested without a database
and `scripts/summarize_test.py` is only the reader and printer. The metric that
decides whether a configuration pays is tokens per *successful line*, not per
row: a setting that stops more rows early is cheap per row but may deliver
fewer lines.
"""
from typing import Iterable

# The two configurations the production comparison is about.
CONFIGS = {
    "A  line, compact OFF": ("personalized_line", False),
    "B  line, compact ON": ("personalized_line", True),
}


def _pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _avg(total: float, n: int) -> float | None:
    return round(total / n) if n else None


def summarize(rows: Iterable[dict]) -> dict:
    rows = list(rows)
    n = len(rows)
    called = [r for r in rows if r.get("stage4_called")]
    lines = sum(1 for r in rows if r.get("line_generated"))
    total = sum(r.get("total_tokens", 0) for r in rows)
    return {
        "rows": n,
        "lines": lines,
        "line_pct": _pct(lines, n),
        "stage1_stop_pct": _pct(sum(1 for r in rows if r.get("stage1_stopped")), n),
        "stage4_call_pct": _pct(len(called), n),
        "contact_issue_pct": _pct(sum(1 for r in rows if r.get("contact_issue")), n),
        "hold_pct": _pct(sum(1 for r in rows if r.get("hold")), n),
        "avg_tokens_per_row": _avg(total, n),
        # The deciding metric: everything spent, divided by what it produced.
        "tokens_per_line": _avg(total, lines),
        "avg_stage1_tokens": _avg(sum(r.get("stage1_tokens", 0) for r in rows), n),
        "avg_stage4_tokens_per_row": _avg(sum(r.get("stage4_tokens", 0) for r in rows), n),
        "avg_stage4_tokens_per_call": _avg(sum(r.get("stage4_tokens", 0) for r in called), len(called)),
        # Of the rows that reached stage 4, the share that needed a re-ask or
        # ended with the line dropped for an unsupported claim.
        "retry_rate_pct": _pct(sum(1 for r in called if r.get("retry_count", 0) > 0), len(called)),
        "grounding_failure_pct": _pct(sum(1 for r in called if r.get("grounding_failure")), len(called)),
        "blank_pct": _pct(n - lines, n),
    }


def by_config(rows: Iterable[dict]) -> dict[str, dict]:
    """Summaries for configuration A and B, plus any other combination seen."""
    rows = [r for r in rows if r.get("output_mode") is not None]
    out: dict[str, dict] = {}
    seen: set[tuple] = set()
    for label, (mode, compact) in CONFIGS.items():
        group = [r for r in rows if r["output_mode"] == mode and bool(r.get("compact_research")) is compact]
        seen.add((mode, compact))
        out[label] = summarize(group)
    for mode, compact in sorted({(r["output_mode"], bool(r.get("compact_research"))) for r in rows} - seen):
        out[f"other: {mode}, compact {'ON' if compact else 'OFF'}"] = summarize(
            [r for r in rows if r["output_mode"] == mode and bool(r.get("compact_research")) is compact]
        )
    return out


LABELS = [
    ("rows", "rows processed"),
    ("lines", "personalized lines generated"),
    ("line_pct", "line generation %"),
    ("tokens_per_line", "TOTAL TOKENS / SUCCESSFUL LINE"),
    ("avg_tokens_per_row", "avg total tokens / row"),
    ("avg_stage1_tokens", "avg stage 1 tokens / row"),
    ("avg_stage4_tokens_per_row", "avg stage 4 tokens / row"),
    ("avg_stage4_tokens_per_call", "avg stage 4 tokens / stage 4 call"),
    ("stage1_stop_pct", "stage 1 stop %"),
    ("stage4_call_pct", "stage 4 call %"),
    ("contact_issue_pct", "contact issue %"),
    ("hold_pct", "hold %"),
    ("retry_rate_pct", "retry rate % (of stage 4 calls)"),
    ("grounding_failure_pct", "grounding failure % (of stage 4 calls)"),
    ("blank_pct", "blank rate %"),
]


def render(report: dict[str, dict]) -> str:
    names = list(report)
    width = max(len(label) for _, label in LABELS) + 2
    lines = [" " * width + "".join(f"{name:>26}" for name in names)]
    for key, label in LABELS:
        cells = "".join(
            f"{'-' if report[name][key] is None else report[name][key]:>26}" for name in names
        )
        lines.append(f"{label:<{width}}{cells}")
    return "\n".join(lines)
