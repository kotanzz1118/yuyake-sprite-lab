# Forecast Lab — TAIL_SPIKE_V2 Sharded Acquisition Gate

Frozen on 2026-09-08 JST before this acquisition produced any extension outcome score.

## Immutable research specification

- Universe: the inherited 4,717-code pre-extension frozen union.
- Universe decompressed CSV SHA-256: `30baf3a515967f49963a6162c2f766e99fc1a4ea9091c7ac5d1bfbb16dfca502`.
- Rule: `PULLBACK_V1 AND mom_pct >= 0.98`.
- The 0.98 threshold may not be tuned on this extension.
- Raw acquisition window: 2026-05-01 through 2026-09-07, inclusive.
- Signal evaluation begins 2026-06-16.
- 2026-09-07 is the last completed Tokyo session available at freeze time; 2026-09-08 intraday data are excluded.
- Source data: Yahoo chart-v8 raw Open, High, Low, Close, Volume and split events only. Dividend-adjusted Close is neither requested nor used.

## Acquisition separation

The ordered frozen universe is split deterministically into 64 disjoint shards by `index modulo 64`. Each acquisition job saves the exact vendor response bytes in compressed NDJSON, parsed raw OHLCV, split events, an attempt ledger, and a shard manifest. No signal or outcome calculation exists in acquisition mode.

## Quality gate fixed before results

The evaluator may run only if every check below passes:

1. Exactly 64 manifests and raw-response files exist, one for every shard 0–63.
2. Exactly 4,717 distinct codes were attempted and their set equals the frozen universe.
3. All terminal statuses are `OK` or structural `NO_DATA`; no rate-limit, transport, source, or parse failure remains.
4. At least 3,700 codes and at least 78% of the frozen universe have parsed raw prices.
5. Security × date rows are unique; all raw OHLCV rows are positive/ordered and volume is nonnegative.
6. At least 80 consensus Tokyo sessions exist across the acquisition window and at least 55 occur in the evaluation window.
7. The last consensus session is exactly 2026-09-07.
8. Every evaluation consensus date has at least 97% of the peak daily code coverage.
9. Split ratios are finite and positive, split events are unique, and all split codes belong to the frozen universe.
10. Split-only normalization is identical after row shuffling and when run one security at a time (`ROW_ORDER_INVARIANCE` and `ADJUSTMENT_GROUP_ISOLATION`).

If any check fails, the frozen evaluator is skipped. The acquisition failure remains recorded, no threshold changes are allowed, and no near-live result is claimed.

## Frozen evaluator

Only after the gate passes, compute features known at close t, require exact exchange-session support, enter at t+1 Open, and evaluate the primary endpoint `Close[t+5] / Open[t+1] - 1 >= 20%`. Compare with other `PULLBACK_V1` observations and the broad eligible market within Date × prior-volatility quintile × prior-liquidity quintile. Report event counts, matched lift, Wilson interval, security-cluster bootstrap, mean, median, trimmed mean, Huber mean, downside probabilities and lower-tail expected shortfall. Event/tail probability and directional expected return remain separate conclusions.
