"""Tests for daily idea report generation."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def report_module():
    """Load generate_daily_idea_report.py as a module."""
    script_path = Path(__file__).resolve().parents[1] / "generate_daily_idea_report.py"
    spec = importlib.util.spec_from_file_location("generate_daily_idea_report", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load generate_daily_idea_report.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_latest_file_ignores_history(report_module, tmp_path: Path):
    current = tmp_path / "market_breadth_2026-05-16.json"
    history = tmp_path / "market_breadth_history.json"
    _write_json(current, {"ok": True})
    _write_json(history, {"history": []})

    assert report_module.latest_file(tmp_path, "market_breadth_*.json") == current


def test_build_summary_from_current_artifact_shapes(report_module, tmp_path: Path):
    _write_json(
        tmp_path / "exposure_posture_2026-05-16.json",
        {
            "recommendation": "CASH_PRIORITY",
            "exposure_ceiling_pct": 4,
            "participation": "NARROW",
            "bias": "VALUE",
            "confidence": "LOW",
            "rationale": "Capital preservation is the priority.",
        },
    )
    _write_json(
        tmp_path / "market_breadth_2026-05-16.json",
        {"composite": {"composite_score": 32.4, "zone": "Weakening"}},
    )
    _write_json(
        tmp_path / "uptrend_analysis_2026-05-16.json",
        {"composite": {"composite_score": 15.9, "zone": "Bear"}},
    )
    _write_json(
        tmp_path / "sector_rotation_2026-05-16.json",
        {
            "groups": {"regime": "balanced", "score": 59},
            "cycle_phase": {"phase": "mid", "confidence": "low"},
            "ranking": [
                {"rank": 1, "sector": "Energy", "ratio_pct": 60.2, "status": "Overbought"},
                {"rank": 2, "sector": "Technology", "ratio_pct": 32.4, "status": "Normal"},
                {"rank": 3, "sector": "Industrials", "ratio_pct": 25.5, "status": "Normal"},
                {"rank": 11, "sector": "Utilities", "ratio_pct": 6.2, "status": "Oversold"},
            ],
            "overbought": [{"sector": "Energy", "ratio_pct": 60.2}],
            "oversold": [{"sector": "Utilities", "ratio_pct": 6.2}],
            "trends": {"uptrend_count": 0, "downtrend_count": 11},
        },
    )

    artifacts = report_module.load_artifacts(tmp_path)
    summary = report_module.build_summary(artifacts, date(2026, 5, 16))

    assert summary["market_permission"]["recommendation"] == "CASH_PRIORITY"
    assert summary["market_permission"]["breadth_score"] == 32.4
    assert summary["sector_rotation"]["group_regime"] == "balanced"
    assert summary["sector_rotation"]["top_sectors"][0]["sector"] == "Energy"


def test_extracts_vcp_and_canslim_candidates(report_module):
    artifacts = {
        "vcp": {
            "results": [
                {
                    "symbol": "NVDA",
                    "sector": "Technology",
                    "composite_score": 91.2,
                    "pattern_type": "Textbook VCP",
                    "execution_state": "Pre-breakout",
                    "vcp_pattern": {"pivot_price": 120.5},
                    "relative_strength": {"rs_rank_estimate": 95},
                }
            ]
        },
        "canslim": {
            "results": [
                {
                    "symbol": "META",
                    "sector": "Communication Services",
                    "composite_score": 82.8,
                    "rating": "Exceptional",
                    "rating_description": "Outstanding fundamentals",
                    "components": {"L": {"details": {"rs_rank": 88}}},
                }
            ]
        },
    }

    candidates = report_module.extract_watchlist_candidates(artifacts)

    assert [c["symbol"] for c in candidates] == ["NVDA", "META"]
    assert candidates[0]["timing_state"] == "Ready Now"
    assert candidates[1]["entry_reference"] == "10-week MA / valid base"


def test_generate_markdown_has_required_sections(report_module):
    summary = {
        "report_date": "2026-05-16",
        "generated_at": "2026-05-16T12:00:00+00:00",
        "market_permission": {
            "recommendation": "CASH_PRIORITY",
            "exposure_ceiling_pct": 4,
            "participation": "NARROW",
            "bias": "VALUE",
            "confidence": "LOW",
            "rationale": "Capital preservation is the priority.",
            "breadth_score": 32.4,
            "breadth_zone": "Weakening",
            "uptrend_score": 15.9,
            "uptrend_zone": "Bear",
        },
        "sector_rotation": {
            "group_regime": "balanced",
            "group_score": 59,
            "cycle_phase": "mid",
            "cycle_confidence": "low",
            "uptrend_count": 0,
            "downtrend_count": 11,
            "top_sectors": [{"sector": "Energy", "ratio_pct": 60.2, "status": "Overbought"}],
            "bottom_sectors": [{"sector": "Utilities", "ratio_pct": 6.2, "status": "Oversold"}],
            "overbought": [],
            "oversold": [],
        },
        "watchlist_candidates": [],
        "missing_candidate_sources": ["vcp", "canslim"],
    }

    markdown = report_module.generate_markdown(summary)

    assert "## Market Permission" in markdown
    assert "## Sector Rotation" in markdown
    assert "## Stocks To Watch" in markdown
    assert "## EMA Pullback Watch" in markdown
    assert "CASH_PRIORITY" in markdown


def test_write_report_creates_markdown_and_json(report_module, tmp_path: Path):
    summary = {
        "report_date": "2026-05-16",
        "generated_at": "2026-05-16T12:00:00+00:00",
        "market_permission": {},
        "sector_rotation": {},
        "watchlist_candidates": [],
        "missing_candidate_sources": [],
    }

    md_path, json_path = report_module.write_report(summary, "# Report", tmp_path)

    assert md_path.exists()
    assert json_path.exists()
    assert json.loads(json_path.read_text(encoding="utf-8"))["report_date"] == "2026-05-16"
