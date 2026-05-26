#!/usr/bin/env python3
"""Generate a daily/ad hoc idea report from existing skill JSON artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ARTIFACT_PATTERNS = {
    "exposure": "exposure_posture_*.json",
    "sector": "sector_rotation_*.json",
    "breadth": "market_breadth_*.json",
    "uptrend": "uptrend_analysis_*.json",
    "vcp": "vcp_screener_*.json",
    "canslim": "canslim_screener_*.json",
    "theme": "theme_detector_*.json",
}

ACTION_BUCKETS = [
    ("Ready Now", "Regime allows risk and setup is in the entry window"),
    ("Near Trigger", "Valid setup near a pivot or trigger"),
    ("Pullback Watch", "Strong stock returning toward 9 EMA, 21 EMA, or 10-week MA"),
    ("Extended/Missed", "Good stock but unfavorable entry location"),
    ("Avoid", "Fails regime, trend, liquidity, or setup quality gates"),
]


def latest_file(input_dir: Path, pattern: str) -> Path | None:
    """Return the newest matching file, excluding auxiliary history files."""
    matches = [p for p in input_dir.glob(pattern) if "_history" not in p.stem]
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def load_json(path: Path | None) -> dict[str, Any] | None:
    """Load JSON from path, returning None when missing or invalid."""
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_artifacts(input_dir: Path) -> dict[str, dict[str, Any] | None]:
    """Load the latest known report artifacts from input_dir."""
    return {
        name: load_json(latest_file(input_dir, pattern))
        for name, pattern in ARTIFACT_PATTERNS.items()
    }


def _get(data: dict[str, Any] | None, *keys: str, default: Any = "N/A") -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


def _fmt_score(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.1f}"
    if isinstance(value, int):
        return str(value)
    return str(value)


def summarize_market_permission(artifacts: dict[str, dict[str, Any] | None]) -> dict[str, Any]:
    """Build the market permission block."""
    exposure = artifacts.get("exposure")
    breadth = artifacts.get("breadth")
    uptrend = artifacts.get("uptrend")

    return {
        "recommendation": _get(exposure, "recommendation"),
        "exposure_ceiling_pct": _get(exposure, "exposure_ceiling_pct"),
        "participation": _get(exposure, "participation"),
        "bias": _get(exposure, "bias"),
        "confidence": _get(exposure, "confidence"),
        "rationale": _get(exposure, "rationale", default="No exposure posture report found."),
        "breadth_score": _get(breadth, "composite", "composite_score"),
        "breadth_zone": _get(breadth, "composite", "zone"),
        "uptrend_score": _get(uptrend, "composite", "composite_score"),
        "uptrend_zone": _get(uptrend, "composite", "zone"),
    }


def summarize_sector_rotation(sector: dict[str, Any] | None) -> dict[str, Any]:
    """Build sector rotation summary fields."""
    ranking = _get(sector, "ranking", default=[])
    if not isinstance(ranking, list):
        ranking = []
    overbought = _get(sector, "overbought", default=[])
    oversold = _get(sector, "oversold", default=[])
    trends = _get(sector, "trends", default={})

    return {
        "group_regime": _get(sector, "groups", "regime"),
        "group_score": _get(sector, "groups", "score"),
        "cycle_phase": _get(sector, "cycle_phase", "phase"),
        "cycle_confidence": _get(sector, "cycle_phase", "confidence"),
        "top_sectors": ranking[:3],
        "bottom_sectors": ranking[-3:] if ranking else [],
        "overbought": overbought if isinstance(overbought, list) else [],
        "oversold": oversold if isinstance(oversold, list) else [],
        "uptrend_count": _get(trends, "uptrend_count", default="N/A")
        if isinstance(trends, dict)
        else "N/A",
        "downtrend_count": _get(trends, "downtrend_count", default="N/A")
        if isinstance(trends, dict)
        else "N/A",
    }


def _candidate_from_vcp(item: dict[str, Any]) -> dict[str, Any]:
    rs = item.get("relative_strength", {})
    pivot = item.get("vcp_pattern", {}).get("pivot_price")
    state = item.get("execution_state", "N/A")
    bucket = "Ready Now" if state in {"Pre-breakout", "Breakout"} else "Near Trigger"
    if state in {"Extended", "Overextended", "Early-post-breakout"}:
        bucket = "Extended/Missed"
    if state in {"Damaged", "Invalid"}:
        bucket = "Avoid"
    return {
        "symbol": item.get("symbol", "N/A"),
        "source": "VCP",
        "sector": item.get("sector", "N/A"),
        "setup_type": item.get("pattern_type", "VCP"),
        "setup_score": item.get("composite_score", "N/A"),
        "relative_strength": rs.get("rs_rank_estimate", rs.get("score", "N/A"))
        if isinstance(rs, dict)
        else "N/A",
        "timing_state": bucket,
        "entry_reference": f"Pivot {pivot:.2f}" if isinstance(pivot, (int, float)) else "Pivot",
        "reason": state,
    }


def _candidate_from_canslim(item: dict[str, Any]) -> dict[str, Any]:
    l_details = item.get("components", {}).get("L", {}).get("details", {})
    if not isinstance(l_details, dict):
        l_details = {}
    score = item.get("composite_score", "N/A")
    bucket = "Pullback Watch"
    if isinstance(score, (int, float)) and score >= 80:
        bucket = "Near Trigger"
    if isinstance(score, (int, float)) and score < 60:
        bucket = "Avoid"
    return {
        "symbol": item.get("symbol", "N/A"),
        "source": "CANSLIM",
        "sector": item.get("sector", "N/A"),
        "setup_type": item.get("rating", "CANSLIM"),
        "setup_score": score,
        "relative_strength": l_details.get("rs_rank", l_details.get("rs_rating", "N/A")),
        "timing_state": bucket,
        "entry_reference": "10-week MA / valid base",
        "reason": item.get("rating_description", item.get("rating", "N/A")),
    }


def extract_watchlist_candidates(artifacts: dict[str, dict[str, Any] | None]) -> list[dict[str, Any]]:
    """Extract normalized candidates from available scanner outputs."""
    candidates: list[dict[str, Any]] = []

    vcp_results = _get(artifacts.get("vcp"), "results", default=[])
    if isinstance(vcp_results, list):
        candidates.extend(_candidate_from_vcp(item) for item in vcp_results if isinstance(item, dict))

    canslim_results = _get(artifacts.get("canslim"), "results", default=[])
    if isinstance(canslim_results, list):
        candidates.extend(
            _candidate_from_canslim(item) for item in canslim_results if isinstance(item, dict)
        )

    return sorted(
        candidates,
        key=lambda c: c["setup_score"] if isinstance(c.get("setup_score"), (int, float)) else -1,
        reverse=True,
    )


def build_summary(artifacts: dict[str, dict[str, Any] | None], report_date: date) -> dict[str, Any]:
    """Build a structured report summary."""
    return {
        "schema_version": "1.0",
        "report_date": report_date.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_permission": summarize_market_permission(artifacts),
        "sector_rotation": summarize_sector_rotation(artifacts.get("sector")),
        "watchlist_candidates": extract_watchlist_candidates(artifacts),
        "ema_pullback_candidates": [],
        "missing_candidate_sources": [
            name
            for name in ["vcp", "canslim"]
            if artifacts.get(name) is None
        ],
    }


def _sector_list(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "N/A"
    parts = []
    for row in rows:
        sector = row.get("sector", "N/A")
        ratio = row.get("ratio_pct", "N/A")
        status = row.get("status", "")
        suffix = f", {status}" if status else ""
        parts.append(f"{sector} ({_fmt_score(ratio)}%{suffix})")
    return "; ".join(parts)


def generate_markdown(summary: dict[str, Any]) -> str:
    """Render the report summary as Markdown."""
    market = summary["market_permission"]
    sector = summary["sector_rotation"]
    candidates = summary["watchlist_candidates"]

    lines = [
        f"# Daily Idea Report - {summary['report_date']}",
        "",
        "## Market Permission",
        "",
        f"- **Recommendation:** {market['recommendation']}",
        f"- **Exposure ceiling:** {market['exposure_ceiling_pct']}%",
        f"- **Participation:** {market['participation']}",
        f"- **Bias:** {market['bias']}",
        f"- **Confidence:** {market['confidence']}",
        f"- **Breadth:** {_fmt_score(market['breadth_score'])} ({market['breadth_zone']})",
        f"- **Uptrend:** {_fmt_score(market['uptrend_score'])} ({market['uptrend_zone']})",
        f"- **Rationale:** {market['rationale']}",
        "",
        "## Sector Rotation",
        "",
        f"- **Group regime:** {sector['group_regime']} ({sector['group_score']})",
        f"- **Cycle phase:** {sector['cycle_phase']} ({sector['cycle_confidence']} confidence)",
        f"- **Sector trends:** {sector['uptrend_count']} up / {sector['downtrend_count']} down",
        f"- **Leaders:** {_sector_list(sector['top_sectors'])}",
        f"- **Laggards:** {_sector_list(sector['bottom_sectors'])}",
        f"- **Overbought:** {_sector_list(sector['overbought'])}",
        f"- **Oversold:** {_sector_list(sector['oversold'])}",
        "",
        "## Stocks To Watch",
        "",
        "| Symbol | Source | Sector | Setup | Score | RS | Timing | Entry Ref | Reason |",
        "|---|---|---|---|---:|---|---|---|---|",
    ]

    if candidates:
        for item in candidates[:25]:
            lines.append(
                "| {symbol} | {source} | {sector} | {setup_type} | {score} | {rs} | "
                "{timing_state} | {entry_reference} | {reason} |".format(
                    symbol=item["symbol"],
                    source=item["source"],
                    sector=item["sector"],
                    setup_type=item["setup_type"],
                    score=_fmt_score(item["setup_score"]),
                    rs=item["relative_strength"],
                    timing_state=item["timing_state"],
                    entry_reference=item["entry_reference"],
                    reason=item["reason"],
                )
            )
    else:
        lines.append("| N/A | N/A | N/A | No VCP/CANSLIM candidate files found | N/A | N/A | N/A | N/A | N/A |")

    lines.extend(
        [
            "",
            "## EMA Pullback Watch",
            "",
            "| Symbol | Setup | RS | Distance To 9 EMA | Distance To 21 EMA | State |",
            "|---|---|---|---:|---:|---|",
            "| N/A | EMA pullback scanner not implemented yet | N/A | N/A | N/A | Pending |",
            "",
            "## Action Buckets",
            "",
            "| Bucket | Meaning |",
            "|---|---|",
        ]
    )
    for bucket, meaning in ACTION_BUCKETS:
        lines.append(f"| {bucket} | {meaning} |")

    missing = summary.get("missing_candidate_sources", [])
    if missing:
        lines.extend(
            [
                "",
                "## Missing Candidate Feeds",
                "",
                ", ".join(missing),
            ]
        )

    lines.extend(["", f"*Generated at {summary['generated_at']}*"])
    return "\n".join(lines)


def write_report(summary: dict[str, Any], markdown: str, output_dir: Path) -> tuple[Path, Path]:
    """Write Markdown and JSON report files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_date = summary["report_date"]
    md_path = output_dir / f"daily_idea_report_{report_date}.md"
    json_path = output_dir / f"daily_idea_report_{report_date}.json"
    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return md_path, json_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate daily idea report from skill outputs")
    parser.add_argument("--input-dir", type=Path, default=Path("reports"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--date", default=date.today().isoformat(), help="Report date YYYY-MM-DD")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_date = date.fromisoformat(args.date)
    artifacts = load_artifacts(args.input_dir)
    summary = build_summary(artifacts, report_date)
    markdown = generate_markdown(summary)
    md_path, json_path = write_report(summary, markdown, args.output_dir)
    print(f"Markdown report: {md_path}")
    print(f"JSON report: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
