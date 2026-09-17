# Forecast Lab external skills scan — 2026-09-17

This note records concepts approved after a fresh external scan. It is not an endorsement of any external project's trading claims.

## High-value additions

### QuantSkills ecosystem

Useful concepts identified:

- survivorship-universe auditing: point-in-time membership, listing/delisting boundaries, stable identities, missing delisting returns;
- backtest overfitting controls: honest trial counts, DSR/PBO/MinTRL concepts, purged/embargoed validation, multiple-testing haircuts;
- factor orthogonalization: remove industry/size/style/existing-factor exposure before claiming security-selection edge;
- IC diagnostics: rank/Pearson IC, horizon decay, subgroup slices and top-basket stability;
- experiment registry: preserve reproducibility evidence and researcher decisions.

Adoption rule: copy no GPL implementation into Forecast Lab. Reimplement only generic methodology or call a separately-audited external tool behind a boundary.

### HKUDS/Vibe-Trading v0.1.15

Useful concepts identified:

- same-universe random-control + out-of-sample strict alpha gate;
- future-row sentinel mutation tests at factor level;
- explicit price-adjustment caliber and source metadata;
- missing-value propagation instead of silently filling plausible values;
- survivorship-bias disclosure must reach the final report;
- PIT fundamentals anchored to filed/available dates;
- group-purged panel cross-validation;
- research-goal/evidence lifecycle and strategy-decay monitoring.

Important caution: recent releases fixed real financial-correctness bugs including future-label leakage, intraday fundamentals look-ahead, price-adjustment ambiguity, missing-value forward fills, point-in-time index membership and source unit inconsistencies. Therefore Forecast Lab may borrow tested ideas but must not delegate canonical research truth to Vibe-Trading.

### Anthropic Financial Services

Useful non-canonical research workflows:

- thesis tracker;
- catalyst calendar;
- earnings preview / earnings analysis;
- model update;
- idea-generation and sector-overview structures.

These are suitable for contextual research, Shadow Watch and article/research production. They are not a substitute for PIT market-data reconstruction or deterministic return computation.

### Official data/MCP connectors

- J-Quants official CLI/Skill remains the preferred Japan-market official adapter where plan/license/timing permit.
- TradingView official MCP is useful for current-market screening, OHLCV, financials, forecasts, documents and alerts, but is not accepted as canonical historical PIT reconstruction.
- Alpha Vantage official MCP can be a secondary cross-check/data source; free usage is too limited for bulk Forecast Lab research.

## v2 implementation priorities

1. Security lifecycle / delisting-return audit.
2. Price-frame metadata contract: source, adjustment caliber, volume unit, as-of/retrieval metadata.
3. Same-universe random-control OOS gate.
4. Top-basket stability / Jaccard diagnostics.
5. Multiple-testing record requirements and promotion gate hooks.
6. Keep DSR/PBO implementations pending independent formula/test verification rather than copying external GPL code.
