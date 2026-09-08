# Forecast Lab — TAIL_SPIKE_V2 Provisional Near-Live Preregistration

Frozen: 2026-09-08 JST, before acquisition/evaluation of the 2026-06-16 onward extension.

## Status
This is a new post-hoc candidate discovered after the 2024-06-17..2026-06-15 forward holdout was inspected. It is NOT confirmed by that holdout. Historical 2017-2022 reverse-era replication is supportive but is also not prospective confirmation.

## Candidate
TAIL_SPIKE_V2 = PULLBACK_V1 AND mom_pct >= 0.98.

PULLBACK_V1 = EVENT_SPIKE_V1 AND r1 in [-5%, 0%].
EVENT_SPIKE_V1 = cross-sectional mom20 percentile > 0.80 AND volume-ratio percentile > 0.80.

All signal inputs are known at t close. Entry is t+1 open. `mom_pct >= 0.98` is frozen; no threshold tuning is allowed on the extension.

## Provisional extension universe
Use the 2026-05-01 J-Quants PIT snapshot already archived before this test. Restrict to Prime/Standard/Growth names in that snapshot. Hold that universe frozen for the extension. This intentionally omits post-2026-05-01 entrants and does not use a later membership snapshot, avoiding membership look-ahead at the cost of incomplete coverage.

## Acquisition/evaluation window
Acquire split-aware Yahoo OHLCV with warmup from 2026-05-01 through 2026-09-08 (or latest complete Tokyo session available). Evaluate signal dates from 2026-06-16 onward, requiring exact t+1..t+5 sessions. Do not use Yahoo dividend-adjusted Adj Close; reconstruct split-only OHLCV from raw OHLC and split events.

## Primary prospective question
Does TAIL_SPIKE_V2 continue to identify the right tail?
Primary tail endpoint: day-5 close return from t+1 open >= +20%.
Secondary endpoints: +10% close hit within t+1..t+5; day-5 close return; MFE/MAE if available.

## Comparators
1. Other PULLBACK_V1 observations matched on Date x prior-volatility quintile x prior-liquidity quintile (incremental-value comparator).
2. Broad eligible market matched on the same cells (context comparator).

## Interpretation
- Tail detection is supported if tail20 probability is above matched PULLBACK controls; because the extension is short, report counts and uncertainty and do not demand conventional significance.
- Directional execution is NOT established merely by tail lift. Mean/median return, downside, and tail concentration must be reported separately.
- A positive result is PROVISIONAL_NEAR_LIVE_OOS because universe membership is frozen at 2026-05-01 rather than updated PIT monthly.
- A negative result is retained as a failure; no threshold retuning on this window.

## Contamination rule
No data dated 2026-06-16 or later may be inspected before this preregistration hash is recorded.

SHA-256 of canonical local preregistration bytes: `b498190c0cca505416577831ec8fb4828c13b6cb729cf460a26d920cf31ce6d4`.
