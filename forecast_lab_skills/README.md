# Forecast Lab Skills Integration v2

This directory is an isolated safety and evaluation layer for importing useful ideas from external finance/quant agent skills into Forecast Lab.

## Non-negotiable boundaries

- Do not modify canonical M86 SQLite artifacts from this package.
- External skills are not trusted merely because they are popular. Reimplement or wrap only the useful behavior after review.
- Every research run must declare an explicit `as_of` timestamp.
- Information may be used only when `available_at <= as_of`.
- LLM output must not be the authoritative source for prices, returns, ranks, probabilities, or backtest metrics.
- Every parameter/feature/threshold experiment is a trial and must be recorded, including failures.
- A score is not a probability. Probability fields remain unset until out-of-sample calibration is independently validated.
- Raw market-data licensing and redistribution restrictions must be preserved at source-adapter boundaries.
- Price inputs used for canonical research must declare source, adjustment caliber and volume unit; unknown semantics fail closed.
- Universe membership, listing/delisting boundaries and missing delisting-return treatment are explicit data-quality checks, not hidden assumptions.

## Core modules

`RunManifest` records trial identity, `as_of`, data snapshots, exact inputs/config hashes, engine version, and skill versions.

`TrialLedger` is append-only JSONL so failed or discarded experiments are not silently forgotten.

`DataPoint` + `assert_point_in_time` provide a minimal PIT guard using explicit information-availability timestamps.

`mutation_leakage_test` supports a hard anti-leakage test: mutate future-only observations and require the historical as-of result to remain bit-for-bit equivalent.

`build_postmortem` provides deterministic 5D/20D-style outcome accounting with raw return, market residual, and sector residual.

`PriceFrameMetadata` requires price-adjustment and volume-unit semantics to be explicit before canonical use.

`SecurityLifecycle`, `audit_universe_membership`, and `missing_delisting_returns` expose survivorship/universe defects rather than silently dropping them.

`same_universe_random_control_gate` compares an out-of-sample candidate metric against random controls drawn from the same universe; this is a placebo/control gate, not proof of alpha.

`top_basket_stability` provides Jaccard stability for ranked candidate baskets so unstable signal membership is visible.

## Adoption policy for external skills

External projects are treated as research references, not as authoritative engines. A candidate is promoted only if it improves at least one of: data quality, reproducibility, bias control, evaluation quality, research speed, or explanatory value without weakening PIT controls.

Priority concepts currently approved for adaptation include:

- official/traceable market data adapters such as J-Quants where licensing and timing allow;
- EDINET-derived company/filing analysis and financial-report vintage reconstruction;
- point-in-time, look-ahead and survivorship-bias controls;
- corporate-action / adjusted-price consistency audits;
- run manifests, trial ledgers and source provenance;
- walk-forward / purge / embargo validation patterns;
- residual-edge and factor-orthogonalization analysis against market, sector, size and style exposures;
- IC decay, subgroup diagnostics and top-basket stability;
- 5D/20D signal postmortems;
- same-universe random/placebo controls;
- bull/bear/risk/data-quality adversarial review;
- calibration audits before any probability claim;
- multiple-testing / backtest-overfit controls after independent formula verification.

Not approved as authoritative inputs: opaque third-party BUY/SELL scores, unverifiable forecast probabilities, indicator-only "high accuracy" prediction claims, or external GPL implementation copied into this package.

## Research scans

See `RESEARCH_SCAN_2026-09-17.md` for the current external-skill scan and source-level adoption notes.

## Test

From the repository root:

```bash
cd forecast_lab_skills
python -m unittest discover -s tests -v
```

The package intentionally uses only the Python standard library in v2. External statistical formulas such as DSR/PBO remain outside the canonical package until independently verified and covered by deterministic tests.
