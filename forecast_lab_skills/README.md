# Forecast Lab Skills Integration v1

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

## v1 modules

`RunManifest` records trial identity, `as_of`, data snapshots, exact inputs/config hashes, engine version, and skill versions.

`TrialLedger` is append-only JSONL so failed or discarded experiments are not silently forgotten.

`DataPoint` + `assert_point_in_time` provide a minimal PIT guard using explicit information-availability timestamps.

`mutation_leakage_test` supports a hard anti-leakage test: mutate future-only observations and require the historical as-of result to remain bit-for-bit equivalent.

`build_postmortem` provides deterministic 5D/20D-style outcome accounting with raw return, market residual, and sector residual.

## Adoption policy for external skills

External projects are treated as research references, not as authoritative engines. A candidate is promoted only if it improves at least one of: data quality, reproducibility, bias control, evaluation quality, research speed, or explanatory value without weakening PIT controls.

Priority concepts currently approved for adaptation include:

- official/traceable market data adapters such as J-Quants where licensing and timing allow;
- EDINET-derived company/filing analysis;
- point-in-time, look-ahead and survivorship-bias controls;
- run manifests, trial ledgers and source provenance;
- walk-forward / purge / embargo validation patterns;
- residual-edge analysis against market and sector benchmarks;
- 5D/20D signal postmortems;
- bull/bear/risk/data-quality adversarial review;
- calibration audits before any probability claim.

Not approved as authoritative inputs: opaque third-party BUY/SELL scores, unverifiable forecast probabilities, or indicator-only "high accuracy" prediction claims without frozen out-of-sample validation.

## Test

From the repository root:

```bash
cd forecast_lab_skills
python -m unittest discover -s tests -v
```

The package intentionally uses only the Python standard library in v1.
