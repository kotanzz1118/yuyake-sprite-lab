from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, MutableSequence, Sequence


def _parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and normalize it to UTC."""
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise ValueError(f"timezone required: {value}")
    return dt.astimezone(timezone.utc)


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return sha256(stable_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class DataPoint:
    """A research input with explicit information-availability time."""

    key: str
    value: Any
    available_at: str
    source: str
    period_end: str | None = None
    published_at: str | None = None
    retrieved_at: str | None = None

    def validate_for(self, as_of: str) -> None:
        if _parse_ts(self.available_at) > _parse_ts(as_of):
            raise ValueError(
                f"look-ahead detected for {self.key}: available_at={self.available_at} > as_of={as_of}"
            )


def assert_point_in_time(records: Iterable[DataPoint], as_of: str) -> None:
    for record in records:
        record.validate_for(as_of)


@dataclass(frozen=True)
class RunManifest:
    trial_id: str
    as_of: str
    engine_version: str
    data_snapshot: Mapping[str, str]
    skill_versions: Mapping[str, str]
    config: Mapping[str, Any]
    inputs: Mapping[str, Any]
    created_at: str

    @classmethod
    def create(
        cls,
        *,
        trial_id: str,
        as_of: str,
        engine_version: str,
        data_snapshot: Mapping[str, str],
        skill_versions: Mapping[str, str],
        config: Mapping[str, Any],
        inputs: Mapping[str, Any],
        created_at: str | None = None,
    ) -> "RunManifest":
        _parse_ts(as_of)
        created = created_at or datetime.now(timezone.utc).isoformat()
        _parse_ts(created)
        return cls(
            trial_id=trial_id,
            as_of=as_of,
            engine_version=engine_version,
            data_snapshot=dict(data_snapshot),
            skill_versions=dict(skill_versions),
            config=dict(config),
            inputs=dict(inputs),
            created_at=created,
        )

    @property
    def input_sha256(self) -> str:
        return sha256_json(self.inputs)

    @property
    def config_sha256(self) -> str:
        return sha256_json(self.config)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["input_sha256"] = self.input_sha256
        payload["config_sha256"] = self.config_sha256
        return payload

    def write(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


class TrialLedger:
    """Append-only JSONL ledger for every research trial, including failures."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, entry: Mapping[str, Any]) -> None:
        required = {"trial_id", "created_at", "status"}
        missing = required - set(entry)
        if missing:
            raise ValueError(f"trial ledger missing required fields: {sorted(missing)}")
        _parse_ts(str(entry["created_at"]))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(stable_json(dict(entry)) + "\n")


def mutation_leakage_test(
    *,
    baseline_input: Sequence[Any],
    evaluate: Callable[[Sequence[Any]], Any],
    mutate_future: Callable[[MutableSequence[Any]], None],
) -> tuple[bool, Any, Any]:
    """PASS only if future-only mutation cannot change the historical as-of result."""
    baseline = list(baseline_input)
    baseline_result = evaluate(baseline)
    mutated = list(baseline_input)
    mutate_future(mutated)
    mutated_result = evaluate(mutated)
    return baseline_result == mutated_result, baseline_result, mutated_result


def _pct_return(start: float, end: float) -> float:
    if start == 0:
        raise ValueError("start price/index cannot be zero")
    return (end / start - 1.0) * 100.0


@dataclass(frozen=True)
class PostmortemResult:
    horizon_sessions: int
    raw_return_pct: float
    market_return_pct: float | None
    sector_return_pct: float | None
    market_residual_pct: float | None
    sector_residual_pct: float | None
    label: str


def build_postmortem(
    *,
    horizon_sessions: int,
    security_start: float,
    security_end: float,
    market_start: float | None = None,
    market_end: float | None = None,
    sector_start: float | None = None,
    sector_end: float | None = None,
    target_pct: float = 10.0,
) -> PostmortemResult:
    if horizon_sessions <= 0:
        raise ValueError("horizon_sessions must be positive")

    raw = _pct_return(security_start, security_end)
    market = None
    sector = None
    if (market_start is None) != (market_end is None):
        raise ValueError("market_start and market_end must be supplied together")
    if (sector_start is None) != (sector_end is None):
        raise ValueError("sector_start and sector_end must be supplied together")
    if market_start is not None and market_end is not None:
        market = _pct_return(market_start, market_end)
    if sector_start is not None and sector_end is not None:
        sector = _pct_return(sector_start, sector_end)

    if raw >= target_pct:
        label = "target_hit"
    elif raw > 0:
        label = "positive_no_target"
    else:
        label = "failed_or_negative"

    return PostmortemResult(
        horizon_sessions=horizon_sessions,
        raw_return_pct=raw,
        market_return_pct=market,
        sector_return_pct=sector,
        market_residual_pct=None if market is None else raw - market,
        sector_residual_pct=None if sector is None else raw - sector,
        label=label,
    )
