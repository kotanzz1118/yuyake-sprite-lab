from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Iterable, Mapping, Sequence


_ALLOWED_ADJUSTMENT = {"raw", "split_adjusted", "total_return", "unknown"}
_ALLOWED_VOLUME_UNITS = {"shares", "lots", "contracts", "currency", "unknown"}


@dataclass(frozen=True)
class PriceFrameMetadata:
    source: str
    adjustment_caliber: str
    volume_unit: str
    retrieved_at: str
    as_of: str | None = None

    def validate(self, *, require_known_adjustment: bool = True, require_known_volume_unit: bool = True) -> None:
        if not self.source.strip():
            raise ValueError("price source is required")
        if self.adjustment_caliber not in _ALLOWED_ADJUSTMENT:
            raise ValueError(f"unsupported adjustment caliber: {self.adjustment_caliber}")
        if self.volume_unit not in _ALLOWED_VOLUME_UNITS:
            raise ValueError(f"unsupported volume unit: {self.volume_unit}")
        if require_known_adjustment and self.adjustment_caliber == "unknown":
            raise ValueError("adjustment caliber must be known for canonical research")
        if require_known_volume_unit and self.volume_unit == "unknown":
            raise ValueError("volume unit must be known for canonical research")


@dataclass(frozen=True)
class SecurityLifecycle:
    code: str
    listed_on: date
    delisted_on: date | None = None

    def eligible_on(self, session: date) -> bool:
        if session < self.listed_on:
            return False
        if self.delisted_on is not None and session > self.delisted_on:
            return False
        return True


@dataclass(frozen=True)
class UniverseAuditFinding:
    code: str
    session: date
    problem: str


def audit_universe_membership(
    *,
    membership: Mapping[date, Iterable[str]],
    lifecycles: Mapping[str, SecurityLifecycle],
) -> list[UniverseAuditFinding]:
    findings: list[UniverseAuditFinding] = []
    for session, codes in membership.items():
        for code in codes:
            lifecycle = lifecycles.get(code)
            if lifecycle is None:
                findings.append(UniverseAuditFinding(code, session, "missing_lifecycle"))
                continue
            if not lifecycle.eligible_on(session):
                if session < lifecycle.listed_on:
                    problem = "present_before_listing"
                else:
                    problem = "present_after_delisting"
                findings.append(UniverseAuditFinding(code, session, problem))
    return findings


def missing_delisting_returns(
    *,
    lifecycles: Mapping[str, SecurityLifecycle],
    delisting_returns: Mapping[str, float],
    start: date,
    end: date,
) -> list[str]:
    missing: list[str] = []
    for code, lifecycle in lifecycles.items():
        if lifecycle.delisted_on is None:
            continue
        if start <= lifecycle.delisted_on <= end and code not in delisting_returns:
            missing.append(code)
    return sorted(missing)


@dataclass(frozen=True)
class RandomControlGateResult:
    candidate_metric: float
    control_median: float
    control_quantile: float
    required_quantile: float
    passed: bool


def _nearest_rank_quantile(values: Sequence[float], q: float) -> float:
    if not values:
        raise ValueError("at least one random-control value is required")
    if not 0.0 < q <= 1.0:
        raise ValueError("q must be in (0, 1]")
    ordered = sorted(float(v) for v in values)
    rank = max(1, int((len(ordered) * q) + 0.999999999))
    return ordered[min(rank - 1, len(ordered) - 1)]


def same_universe_random_control_gate(
    *,
    candidate_oos_metric: float,
    random_control_oos_metrics: Sequence[float],
    required_quantile: float = 0.95,
) -> RandomControlGateResult:
    threshold = _nearest_rank_quantile(random_control_oos_metrics, required_quantile)
    return RandomControlGateResult(
        candidate_metric=float(candidate_oos_metric),
        control_median=float(median(random_control_oos_metrics)),
        control_quantile=threshold,
        required_quantile=required_quantile,
        passed=float(candidate_oos_metric) > threshold,
    )


@dataclass(frozen=True)
class BasketStability:
    intersection: int
    union: int
    jaccard: float


def top_basket_stability(previous: Iterable[str], current: Iterable[str]) -> BasketStability:
    prev = set(previous)
    curr = set(current)
    union = prev | curr
    intersection = prev & curr
    score = 1.0 if not union else len(intersection) / len(union)
    return BasketStability(len(intersection), len(union), score)
