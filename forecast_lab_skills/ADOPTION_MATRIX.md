# External Skill Adoption Matrix

This matrix records the current integration decision. Useful methods are adapted under Forecast Lab rules rather than blindly vendored.

| Source / family | Decision | Adopt | Reject / quarantine |
|---|---|---|---|
| J-Quants official CLI / skill | Adopt adapter concept | official data access, symbol/master/price/fundamental retrieval where plan/licensing permits | do not assume free tier is current; do not redistribute raw licensed data |
| ml4t skills | Strong adopt | PIT, look-ahead, survivorship, walk-forward, purge/embargo, multiple-testing, governance patterns | do not import methods without local regression tests |
| stock-trade-analysis-skills | Strong adopt | `as_of` contract, run manifest, trial ledger, leakage mutation testing, calibrated-probability discipline | no direct trust in generated numbers |
| claude-trading-skills | Selective adopt | signal postmortem, residual edge, regime context, data-quality review | no automatic trading decisions |
| Anthropic financial-services patterns | Selective adopt | earnings/comps/research workflow and structured evidence collection | do not treat agent synthesis as numeric ground truth |
| TradingAgents | Architecture-only | bull/bear/risk/adversarial separation | no wholesale multi-agent execution or embedded forecast claims |
| EDINET-focused Japanese equity projects | Selective adopt | filings, segment/shareholder/peer analysis ideas | verify disclosure availability time and source lineage locally |
| Opaque forecast-score / 3-day prediction skills | Reject | none | unverifiable probabilities, weak PIT controls, no independent OOS evidence |

## Promotion gates

A new external skill or method is eligible for Forecast Lab only after all applicable gates pass:

1. source and license boundary documented;
2. explicit `as_of`/`available_at` semantics defined;
3. deterministic numeric path separated from LLM prose;
4. frozen regression fixture passes;
5. future-data mutation cannot change prior results;
6. delisted/listed universe behavior is documented;
7. parameter search is recorded in the trial ledger;
8. any probability output passes frozen out-of-sample calibration tests;
9. canonical SQLite is not modified by the integration layer;
10. human-readable failure reason is emitted when a gate fails.
