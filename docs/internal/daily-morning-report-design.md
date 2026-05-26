# Daily Morning Idea Report Design

Status: draft v0.1
Last updated: 2026-05-16

## Purpose

Create a daily or ad hoc report that starts with market permission, then turns
sector rotation and setup scanners into a small, ranked list of stocks to watch.
The report should be useful before the open, during a midday review, or after
the close when building the next day's watchlist.

The report is not a buy/sell engine. It is an idea funnel:

1. Decide whether new equity risk is allowed.
2. Identify which sectors/themes deserve attention.
3. Rank stock candidates by setup quality, timing, and relative strength.
4. Separate candidates into action buckets.
5. Feed accepted ideas into trader-memory-core for later review.

## Current Repository Building Blocks

| Report block | Existing source | Current status |
|---|---|---|
| Market breadth | `skills/market-breadth-analyzer/scripts/market_breadth_analyzer.py` | Works with public data |
| Uptrend participation | `skills/uptrend-analyzer/scripts/uptrend_analyzer.py` | Works with public data |
| Sector rotation | `skills/sector-analyst/scripts/analyze_sector_rotation.py` | Works with public data |
| Exposure gate | `skills/exposure-coach/scripts/calculate_exposure.py` | Now parses current breadth/uptrend/sector JSON |
| Themes | `skills/theme-detector/scripts/theme_detector.py` | Public mode works, FINVIZ improves coverage |
| CAN SLIM candidates | `skills/canslim-screener/scripts/screen_canslim.py` | Requires FMP |
| VCP / Minervini candidates | `skills/vcp-screener/scripts/screen_vcp.py` | Requires FMP |
| Trade planning | `skills/breakout-trade-planner/scripts/plan_breakout_trades.py` and `skills/position-sizer/scripts/position_sizer.py` | Works after candidate selection |
| Memory loop | `skills/trader-memory-core/scripts/thesis_ingest.py` | Available for accepted theses |

## First Report Contract

### 1. Market Permission

Inputs:

- Latest market breadth JSON.
- Latest uptrend analyzer JSON.
- Latest sector rotation JSON.
- Optional top-risk, macro-regime, FTD, theme, and institutional-flow JSON.

Output fields:

- `exposure_recommendation`: `NEW_ENTRY_ALLOWED`, `REDUCE_ONLY`, or `CASH_PRIORITY`.
- `exposure_ceiling_pct`.
- `participation`: `BROAD`, `MODERATE`, or `NARROW`.
- `bias`: `GROWTH`, `VALUE`, `DEFENSIVE`, or `NEUTRAL`.
- One-sentence rationale.

Rule: if the exposure recommendation is `CASH_PRIORITY`, the stock sections
should still build a watchlist, but every candidate is labeled `Watch only`.

### 2. Sector Rotation

Inputs:

- Sector analyst ranking.
- Theme detector output when available.

Output fields:

- Top 3 sectors by uptrend ratio.
- Bottom 3 sectors by uptrend ratio.
- Overbought and oversold sector flags.
- Cyclical vs defensive vs commodity regime.
- Sector trend breadth, especially count of sectors sloping up vs down.

Interpretation:

- Strong sector leadership plus broad participation supports entries.
- Narrow leadership or all sectors sloping down reduces candidate priority.
- Overbought leadership should produce `extended/crowded` warnings, not
automatic long ideas.

### 3. Stocks To Watch

Candidate sources:

- VCP screener for Minervini-style tight bases and pivot proximity.
- CAN SLIM screener for fundamental growth plus leadership.
- Theme detector representative stocks for narrative/sector context.
- FinViz recipes for quick ad hoc screen URLs.

Minimum candidate fields:

- `symbol`
- `company_name`
- `source`: `vcp`, `canslim`, `theme`, `finviz`, or future scanner id.
- `sector`
- `setup_type`
- `setup_score`
- `relative_strength_score`
- `timing_state`: `Ready Now`, `Near Trigger`, `Pullback Watch`, `Extended/Missed`, or `Avoid`.
- `entry_reference`: pivot, 9 EMA, 21 EMA, 50 SMA, or 10-week MA.
- `stop_reference`
- `reason`
- `risk_notes`

### 4. Pullback Watchlist

This is the largest current gap. The repo does not yet have a dedicated
Qullamaggie-style or high-relative-strength EMA pullback scanner.

Target behavior:

- Start from a strong-trend universe: price above 50 SMA and 200 SMA, near
  highs, liquid, and high relative strength.
- Calculate distance to 9 EMA, 21 EMA, 50 SMA, and 10-week MA.
- Detect constructive pullbacks: controlled decline, volume dry-up, no major
  support break, still above key long-term averages.
- Rank candidates that are approaching the 9 EMA or 21 EMA, not already
  breaking down.
- Allow custom relative-strength formulas later.

Initial output buckets:

- `9 EMA touch/watch`: within a configurable band of 9 EMA.
- `21 EMA pullback`: within a configurable band of 21 EMA.
- `10-week MA pullback`: weekly support test for CAN SLIM style entries.
- `Extended`: high RS but too far above short-term averages.
- `Damaged`: lost trend template or undercut key support.

### 5. Action Buckets

The report should end with a compact table:

| Bucket | Meaning |
|---|---|
| Ready Now | Regime allows risk and setup is in entry window |
| Near Trigger | Valid setup within a few percent of trigger |
| Pullback Watch | Strong stock returning toward 9 EMA, 21 EMA, or 10-week MA |
| Extended/Missed | Good stock but unfavorable entry location |
| Avoid | Fails regime, trend, liquidity, or setup quality gates |

## Daily Command Flow

No-key baseline:

```bash
python3 skills/uptrend-analyzer/scripts/uptrend_analyzer.py --output-dir reports/
python3 skills/market-breadth-analyzer/scripts/market_breadth_analyzer.py --output-dir reports/
python3 skills/sector-analyst/scripts/analyze_sector_rotation.py --json --save --output-dir reports/

breadth=$(ls -t reports/market_breadth_20*.json | head -1)
uptrend=$(ls -t reports/uptrend_analysis_20*.json | head -1)
sector=$(ls -t reports/sector_rotation_20*.json | head -1)

python3 skills/exposure-coach/scripts/calculate_exposure.py \
  --breadth "$breadth" \
  --uptrend "$uptrend" \
  --sector "$sector" \
  --output-dir reports/

python3 scripts/generate_daily_idea_report.py \
  --input-dir reports/ \
  --output-dir reports/
```

FMP-enabled expansion:

```bash
python3 skills/vcp-screener/scripts/screen_vcp.py --strict --output-dir reports/
python3 skills/canslim-screener/scripts/screen_canslim.py --max-candidates 35 --output-dir reports/
python3 scripts/generate_daily_idea_report.py --input-dir reports/ --output-dir reports/
```

The report generator reads the latest available JSON artifacts. If VCP or CAN
SLIM outputs are missing, it still emits typed watchlist tables and names the
missing candidate feeds.

## Open Decisions

1. Define what `BCP` means in this project before encoding it as a scanner or
   report section.
2. Decide whether the first report should be a script under `scripts/`, a new
   skill, or an extension of `examples/daily-market-dashboard`.
3. Choose the first relative-strength formula to support:
   - existing VCP Minervini weighted RS,
   - existing CAN SLIM 3m/6m/12m benchmark RS,
   - a custom user-provided formula,
   - or all of the above behind a common interface.
4. Decide whether EMA pullback scanning should use FMP, yfinance, local CSV, or
   a pluggable data adapter.

## Next Implementation Slice

Build a small `daily-idea-report` generator that reads already-produced JSON
files from `reports/`, creates the Market Permission and Sector Rotation
sections, and leaves Stock Watch and Pullback Watch sections as empty but typed
tables until FMP-backed scanners or local price data are available.
