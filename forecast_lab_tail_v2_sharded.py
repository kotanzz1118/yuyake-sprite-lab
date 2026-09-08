from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import math
import os
import random
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


UNIVERSE_ENCODED_SHA256 = "316d958078d5cba9fb22f2ca6fe972ea8e506182da7e09d051a622a703bb1718"
UNIVERSE_CSV_SHA256 = "30baf3a515967f49963a6162c2f766e99fc1a4ea9091c7ac5d1bfbb16dfca502"
UNIVERSE_SIZE = 4717
SHARD_COUNT = 64
RAW_START = date(2026, 5, 1)
RAW_END_EXCLUSIVE = date(2026, 9, 8)
EVAL_START = date(2026, 6, 16)
LAST_COMPLETE_SESSION_CAP = date(2026, 9, 7)
EPS = 1e-12
TOKYO = ZoneInfo("Asia/Tokyo")
SOURCE = "Yahoo chart v8 raw OHLCV + split events"

RAW_COLUMNS = [
    "security_code",
    "ticker",
    "date",
    "open_raw",
    "high_raw",
    "low_raw",
    "close_raw",
    "volume_raw",
    "source",
    "shard_id",
    "retrieved_at_utc",
    "response_sha256",
]
ATTEMPT_COLUMNS = [
    "security_code",
    "ticker",
    "shard_id",
    "status",
    "http_status",
    "request_attempts",
    "rows",
    "first_date",
    "last_date",
    "error_class",
    "error_message",
    "elapsed_seconds",
    "retrieved_at_utc",
    "response_sha256",
]
SPLIT_COLUMNS = [
    "security_code",
    "ticker",
    "split_date",
    "split_ratio",
    "numerator",
    "denominator",
    "source",
    "shard_id",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_safe(payload), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    )


def load_frozen_codes(root: Path) -> list[str]:
    encoded = "".join(
        (root / "forecast_lab_union_chunks" / f"c{i}.txt").read_text().strip()
        for i in range(6)
    )
    assert sha256_bytes(encoded.encode()) == UNIVERSE_ENCODED_SHA256
    packed = base64.b64decode(encoded)
    values: list[int] = []
    current = shift = previous = 0
    for byte in packed:
        current |= (byte & 127) << shift
        if byte & 128:
            shift += 7
            continue
        delta = current // 2 if current % 2 == 0 else -(current // 2) - 1
        previous += delta
        values.append(previous)
        current = shift = 0
    assert current == 0 and shift == 0
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    inverse = {i + 1: char for i, char in enumerate(chars)}

    def decode_code(number: int) -> str:
        result = ""
        while number > 0:
            number, remainder = divmod(number, 37)
            result = inverse[remainder] + result
        return result

    codes = [decode_code(value) for value in values]
    raw_csv = ("security_code\n" + "\n".join(codes) + "\n").encode()
    assert sha256_bytes(raw_csv) == UNIVERSE_CSV_SHA256
    assert len(codes) == UNIVERSE_SIZE and len(set(codes)) == UNIVERSE_SIZE
    return codes


def epoch_at_tokyo_midnight(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=TOKYO).timestamp())


def ticker_for_code(code: str) -> str:
    # The frozen universe is immutable. Seven inherited five-character identifiers are
    # deliberately attempted as-is and will be classified by the source, not silently changed.
    return f"{code}.T"


@dataclass
class FetchResult:
    status: str
    http_status: int | None
    request_attempts: int
    body: bytes | None
    payload: dict[str, Any] | None
    error_class: str
    error_message: str


def fetch_chart(ticker: str) -> FetchResult:
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{quote(ticker, safe='')}"
    params = {
        "period1": epoch_at_tokyo_midnight(RAW_START),
        "period2": epoch_at_tokyo_midnight(RAW_END_EXCLUSIVE),
        "interval": "1d",
        "events": "splits",
        "includeAdjustedClose": "false",
        "includePrePost": "false",
    }
    last_status: int | None = None
    last_body: bytes | None = None
    last_error = ""
    for attempt in range(1, 4):
        try:
            request = Request(
                f"{url}?{urlencode(params)}",
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                    "Accept": "application/json,text/plain,*/*",
                    "Accept-Language": "en-US,en;q=0.8",
                },
            )
            with urlopen(request, timeout=35) as response:
                last_status = response.status
                last_body = response.read()
            if last_status == 429:
                if attempt < 3:
                    time.sleep(8 * attempt + random.random() * 4)
                    continue
                return FetchResult(
                    "RATE_LIMIT",
                    429,
                    attempt,
                    last_body,
                    None,
                    "HTTP_429",
                    "Yahoo rate limit after three attempts",
                )
            if last_status >= 500:
                if attempt < 3:
                    time.sleep(3 * attempt + random.random() * 2)
                    continue
                return FetchResult(
                    "RETRY_EXHAUSTED",
                    last_status,
                    attempt,
                    last_body,
                    None,
                    "HTTP_5XX",
                    f"HTTP {last_status}",
                )
            if last_status in (404, 422):
                return FetchResult(
                    "NO_DATA",
                    last_status,
                    attempt,
                    last_body,
                    None,
                    "HTTP_NO_DATA",
                    f"HTTP {last_status}",
                )
            if last_status >= 400:
                raise HTTPError(url, last_status, f"HTTP {last_status}", {}, None)
            payload = json.loads((last_body or b"").decode("utf-8"))
            chart = payload.get("chart") or {}
            chart_error = chart.get("error")
            result = chart.get("result") or []
            if chart_error or not result:
                description = (chart_error or {}).get("description", "empty chart result")
                lowered = description.lower()
                if any(word in lowered for word in ("delisted", "no data", "not found")):
                    status = "NO_DATA"
                    error_class = "YAHOO_NO_DATA"
                else:
                    status = "SOURCE_ERROR"
                    error_class = "YAHOO_CHART_ERROR"
                return FetchResult(
                    status,
                    last_status,
                    attempt,
                    last_body,
                    payload,
                    error_class,
                    description[:500],
                )
            return FetchResult("OK", last_status, attempt, last_body, payload, "", "")
        except HTTPError as exc:
            last_status = exc.code
            try:
                last_body = exc.read()
            except Exception:
                last_body = None
            if exc.code == 429:
                if attempt < 3:
                    time.sleep(8 * attempt + random.random() * 4)
                    continue
                return FetchResult(
                    "RATE_LIMIT", 429, attempt, last_body, None, "HTTP_429",
                    "Yahoo rate limit after three attempts",
                )
            if exc.code in (404, 422):
                return FetchResult(
                    "NO_DATA", exc.code, attempt, last_body, None, "HTTP_NO_DATA",
                    f"HTTP {exc.code}",
                )
            last_error = f"HTTPError: {exc}"
            if attempt < 3:
                time.sleep(3 * attempt + random.random() * 2)
                continue
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < 3:
                time.sleep(3 * attempt + random.random() * 2)
                continue
    return FetchResult(
        "RETRY_EXHAUSTED",
        last_status,
        3,
        last_body,
        None,
        "TRANSPORT_OR_JSON",
        last_error[:500],
    )


def parse_chart(
    code: str,
    ticker: str,
    shard_id: int,
    retrieved_at: str,
    response_hash: str,
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp") or []
    quotes = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    rows: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        values: dict[str, float | None] = {}
        for source_key, output_key in (
            ("open", "open_raw"),
            ("high", "high_raw"),
            ("low", "low_raw"),
            ("close", "close_raw"),
            ("volume", "volume_raw"),
        ):
            series = quotes.get(source_key) or []
            value = series[index] if index < len(series) else None
            values[output_key] = None if value is None else float(value)
        if values["close_raw"] is None:
            continue
        trading_date = datetime.fromtimestamp(int(timestamp), tz=TOKYO).date()
        if not (RAW_START <= trading_date < RAW_END_EXCLUSIVE):
            continue
        rows.append(
            {
                "security_code": code,
                "ticker": ticker,
                "date": trading_date.isoformat(),
                **values,
                "source": SOURCE,
                "shard_id": shard_id,
                "retrieved_at_utc": retrieved_at,
                "response_sha256": response_hash,
            }
        )
    split_rows: list[dict[str, Any]] = []
    for event in ((result.get("events") or {}).get("splits") or {}).values():
        timestamp = event.get("date")
        if timestamp is None:
            continue
        split_date = datetime.fromtimestamp(int(timestamp), tz=TOKYO).date()
        numerator = event.get("numerator")
        denominator = event.get("denominator")
        ratio = event.get("splitRatio")
        if numerator is not None and denominator not in (None, 0):
            numeric_ratio = float(numerator) / float(denominator)
        else:
            try:
                left, right = str(ratio).split(":", 1)
                numeric_ratio = float(left) / float(right)
            except (TypeError, ValueError, ZeroDivisionError):
                numeric_ratio = float("nan")
        split_rows.append(
            {
                "security_code": code,
                "ticker": ticker,
                "split_date": split_date.isoformat(),
                "split_ratio": numeric_ratio,
                "numerator": numerator,
                "denominator": denominator,
                "source": SOURCE,
                "shard_id": shard_id,
            }
        )
    return rows, split_rows


def acquire(root: Path, output: Path, shard_id: int, shard_count: int) -> None:
    if shard_count != SHARD_COUNT or not 0 <= shard_id < shard_count:
        raise ValueError(f"expected shard_count={SHARD_COUNT} and valid shard_id")
    codes = load_frozen_codes(root)
    shard_codes = [code for index, code in enumerate(codes) if index % shard_count == shard_id]
    output.mkdir(parents=True, exist_ok=True)
    random.seed(20260908 + shard_id)
    initial_delay = (shard_id % 16) * 4 + random.random() * 3
    time.sleep(initial_delay)
    rows: list[dict[str, Any]] = []
    splits: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    raw_response_count = 0
    started = time.monotonic()
    raw_path = output / "vendor_responses.ndjson.gz"
    rate_limit_abort = False
    with gzip.open(raw_path, "wt", encoding="utf-8") as raw_stream:
        for code in shard_codes:
            ticker = ticker_for_code(code)
            request_started = time.monotonic()
            retrieved_at = utc_now()
            if rate_limit_abort:
                fetched = FetchResult(
                    "RATE_LIMIT_ABORTED",
                    429,
                    0,
                    None,
                    None,
                    "SHARD_ABORT_AFTER_HTTP_429",
                    "not requested after this shard reached a terminal Yahoo rate limit",
                )
            else:
                fetched = fetch_chart(ticker)
                if fetched.status == "RATE_LIMIT":
                    rate_limit_abort = True
            response_hash = sha256_bytes(fetched.body) if fetched.body is not None else ""
            raw_stream.write(
                json.dumps(
                    {
                        "security_code": code,
                        "ticker": ticker,
                        "retrieved_at_utc": retrieved_at,
                        "http_status": fetched.http_status,
                        "status": fetched.status,
                        "response_sha256": response_hash,
                        "body_b64": base64.b64encode(fetched.body or b"").decode(),
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
            raw_response_count += 1
            parsed_rows: list[dict[str, Any]] = []
            parsed_splits: list[dict[str, Any]] = []
            status = fetched.status
            error_class = fetched.error_class
            error_message = fetched.error_message
            if fetched.status == "OK" and fetched.payload is not None:
                try:
                    parsed_rows, parsed_splits = parse_chart(
                        code, ticker, shard_id, retrieved_at, response_hash, fetched.payload
                    )
                    if not parsed_rows:
                        status = "NO_DATA"
                        error_class = "EMPTY_PARSED_SERIES"
                        error_message = "chart returned no complete daily close observations"
                except (KeyError, TypeError, ValueError, IndexError) as exc:
                    status = "PARSE_FAIL"
                    error_class = type(exc).__name__
                    error_message = str(exc)[:500]
            rows.extend(parsed_rows)
            splits.extend(parsed_splits)
            attempts.append(
                {
                    "security_code": code,
                    "ticker": ticker,
                    "shard_id": shard_id,
                    "status": status,
                    "http_status": fetched.http_status,
                    "request_attempts": fetched.request_attempts,
                    "rows": len(parsed_rows),
                    "first_date": parsed_rows[0]["date"] if parsed_rows else "",
                    "last_date": parsed_rows[-1]["date"] if parsed_rows else "",
                    "error_class": error_class,
                    "error_message": error_message,
                    "elapsed_seconds": time.monotonic() - request_started,
                    "retrieved_at_utc": retrieved_at,
                    "response_sha256": response_hash,
                }
            )
            if not rate_limit_abort:
                time.sleep(0.75 + random.random() * 0.55)
    pd.DataFrame(rows, columns=RAW_COLUMNS).to_csv(output / "raw_ohlcv.csv.gz", index=False)
    pd.DataFrame(attempts, columns=ATTEMPT_COLUMNS).to_csv(
        output / "acquisition_attempts.csv", index=False
    )
    pd.DataFrame(splits, columns=SPLIT_COLUMNS).to_csv(output / "split_events.csv", index=False)
    statuses = pd.Series([row["status"] for row in attempts]).value_counts().to_dict()
    manifest = {
        "schema_version": 1,
        "mode": "ACQUISITION_ONLY_NO_OUTCOME_SCORING",
        "shard_id": shard_id,
        "shard_count": shard_count,
        "universe_size": UNIVERSE_SIZE,
        "universe_csv_sha256": UNIVERSE_CSV_SHA256,
        "assigned_codes": len(shard_codes),
        "assigned_code_sha256": sha256_bytes(("\n".join(shard_codes) + "\n").encode()),
        "attempt_rows": len(attempts),
        "raw_response_rows": raw_response_count,
        "parsed_price_codes": len({row["security_code"] for row in rows}),
        "parsed_price_rows": len(rows),
        "split_rows": len(splits),
        "status_counts": statuses,
        "raw_start": RAW_START.isoformat(),
        "raw_end_exclusive": RAW_END_EXCLUSIVE.isoformat(),
        "elapsed_seconds": time.monotonic() - started,
        "completed_at_utc": utc_now(),
    }
    write_json(output / "manifest.json", manifest)
    print(json.dumps(manifest, sort_keys=True))


def read_recursive(
    base: Path, filename: str, kind: str
) -> tuple[list[pd.DataFrame], list[dict[str, str]]]:
    paths = sorted(base.rglob(filename))
    frames: list[pd.DataFrame] = []
    failures: list[dict[str, str]] = []
    for path in paths:
        try:
            if kind == "csv":
                frames.append(pd.read_csv(path, dtype={"security_code": str}))
            else:
                raise ValueError(kind)
        except Exception as exc:
            failures.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
    return frames, failures


def audit_vendor_response_files(input_dir: Path) -> tuple[list[str], list[dict[str, str]]]:
    codes: list[str] = []
    failures: list[dict[str, str]] = []
    for path in sorted(input_dir.rglob("vendor_responses.ndjson.gz")):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    item = json.loads(line)
                    code = str(item["security_code"])
                    body = base64.b64decode(item.get("body_b64", ""), validate=True)
                    expected = str(item.get("response_sha256", ""))
                    actual = sha256_bytes(body) if body else ""
                    if expected != actual:
                        raise ValueError(
                            f"response hash mismatch at line {line_number}: {expected} != {actual}"
                        )
                    codes.append(code)
        except Exception as exc:
            failures.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
    return codes, failures


def normalize_split_only(prices: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    result_parts: list[pd.DataFrame] = []
    split_map: dict[str, list[tuple[pd.Timestamp, float]]] = {}
    if not splits.empty:
        for code, group in splits.groupby("security_code", sort=False):
            split_map[str(code)] = [
                (pd.Timestamp(day), float(ratio))
                for day, ratio in zip(group["split_date"], group["split_ratio"])
            ]
    for code, group in prices.groupby("security_code", sort=False):
        part = group.copy()
        dates = pd.to_datetime(part["date"]).to_numpy(dtype="datetime64[ns]")
        factors = np.ones(len(part), dtype=float)
        for split_day, ratio in split_map.get(str(code), []):
            factors[dates < split_day.to_datetime64()] *= ratio
        for raw_name, adjusted_name in (
            ("open_raw", "open_adj"),
            ("high_raw", "high_adj"),
            ("low_raw", "low_adj"),
            ("close_raw", "close_adj"),
        ):
            part[adjusted_name] = pd.to_numeric(part[raw_name], errors="coerce") / factors
        part["volume_adj"] = pd.to_numeric(part["volume_raw"], errors="coerce") * factors
        part["split_future_factor"] = factors
        result_parts.append(part)
    if not result_parts:
        return prices.copy()
    return pd.concat(result_parts, ignore_index=True).sort_values(
        ["security_code", "date"], kind="stable"
    ).reset_index(drop=True)


def frame_hash(frame: pd.DataFrame, columns: Iterable[str]) -> str:
    subset = frame.loc[:, list(columns)].sort_values(
        ["security_code", "date"], kind="stable"
    ).reset_index(drop=True)
    return sha256_bytes(pd.util.hash_pandas_object(subset, index=False).values.tobytes())


def quality_gate(root: Path, input_dir: Path, output: Path) -> bool:
    output.mkdir(parents=True, exist_ok=True)
    frozen_codes = load_frozen_codes(root)
    manifest_paths = sorted(input_dir.rglob("manifest.json"))
    manifests = [json.loads(path.read_text()) for path in manifest_paths]
    raw_frames, raw_read_failures = read_recursive(input_dir, "raw_ohlcv.csv.gz", "csv")
    attempt_frames, attempt_read_failures = read_recursive(
        input_dir, "acquisition_attempts.csv", "csv"
    )
    split_frames, split_read_failures = read_recursive(input_dir, "split_events.csv", "csv")
    vendor_response_codes, vendor_response_failures = audit_vendor_response_files(input_dir)
    raw = pd.concat(raw_frames, ignore_index=True) if raw_frames else pd.DataFrame(columns=RAW_COLUMNS)
    attempts = (
        pd.concat(attempt_frames, ignore_index=True)
        if attempt_frames
        else pd.DataFrame(columns=ATTEMPT_COLUMNS)
    )
    splits = (
        pd.concat(split_frames, ignore_index=True)
        if split_frames
        else pd.DataFrame(columns=SPLIT_COLUMNS)
    )
    for frame in (raw, attempts, splits):
        if "security_code" in frame:
            frame["security_code"] = frame["security_code"].astype(str)
    if not raw.empty:
        raw["date"] = pd.to_datetime(raw["date"]).dt.normalize()
    if not splits.empty:
        splits["split_date"] = pd.to_datetime(splits["split_date"]).dt.normalize()
        splits["split_ratio"] = pd.to_numeric(splits["split_ratio"], errors="coerce")

    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, actual: Any, required: str) -> None:
        checks.append(
            {"check": name, "passed": bool(passed), "actual": actual, "required": required}
        )

    shard_ids = sorted(int(item.get("shard_id", -1)) for item in manifests)
    check("manifest_count", len(manifests) == SHARD_COUNT, len(manifests), f"== {SHARD_COUNT}")
    check("shard_ids", shard_ids == list(range(SHARD_COUNT)), str(shard_ids), "0..63 exactly once")
    check(
        "manifest_universe_hash",
        bool(manifests)
        and all(item.get("universe_csv_sha256") == UNIVERSE_CSV_SHA256 for item in manifests),
        sorted({item.get("universe_csv_sha256") for item in manifests}),
        UNIVERSE_CSV_SHA256,
    )
    attempted_codes = attempts["security_code"].tolist() if not attempts.empty else []
    check("attempt_count", len(attempts) == UNIVERSE_SIZE, len(attempts), f"== {UNIVERSE_SIZE}")
    check(
        "attempt_universe_exact",
        sorted(attempted_codes) == sorted(frozen_codes),
        len(set(attempted_codes).symmetric_difference(frozen_codes)),
        "zero symmetric difference",
    )
    check(
        "attempt_duplicate_codes",
        len(attempted_codes) == len(set(attempted_codes)),
        len(attempted_codes) - len(set(attempted_codes)),
        "== 0",
    )
    status_counts = attempts["status"].value_counts().to_dict() if not attempts.empty else {}
    bad_statuses = {
        status: int(count)
        for status, count in status_counts.items()
        if status not in {"OK", "NO_DATA"}
    }
    check("no_transient_or_parse_failures", not bad_statuses, bad_statuses, "empty")
    check(
        "raw_response_files",
        len(list(input_dir.rglob("vendor_responses.ndjson.gz"))) == SHARD_COUNT,
        len(list(input_dir.rglob("vendor_responses.ndjson.gz"))),
        f"== {SHARD_COUNT}",
    )
    read_failures = raw_read_failures + attempt_read_failures + split_read_failures
    check("all_tabular_files_readable", not read_failures, read_failures, "empty")
    check(
        "raw_response_integrity",
        not vendor_response_failures
        and sorted(vendor_response_codes) == sorted(frozen_codes)
        and len(vendor_response_codes) == len(set(vendor_response_codes)),
        {
            "records": len(vendor_response_codes),
            "unique": len(set(vendor_response_codes)),
            "failures": vendor_response_failures,
        },
        "4,717 unique frozen codes with valid response-body hashes",
    )
    raw_codes = set(raw["security_code"]) if not raw.empty else set()
    check("price_code_floor", len(raw_codes) >= 3700, len(raw_codes), ">= 3700")
    check("price_code_ratio", len(raw_codes) / UNIVERSE_SIZE >= 0.78, len(raw_codes) / UNIVERSE_SIZE, ">= 0.78")
    duplicates = int(raw.duplicated(["security_code", "date"]).sum()) if not raw.empty else 0
    check("unique_security_date", duplicates == 0, duplicates, "== 0")
    required_columns_ok = set(RAW_COLUMNS).issubset(raw.columns)
    check("raw_columns", required_columns_ok, sorted(raw.columns), "all frozen raw columns")
    if not raw.empty:
        numeric = raw[["open_raw", "high_raw", "low_raw", "close_raw", "volume_raw"]].apply(
            pd.to_numeric, errors="coerce"
        )
        invalid_ohlc = (
            numeric[["open_raw", "high_raw", "low_raw", "close_raw"]].isna().any(axis=1)
            | (numeric[["open_raw", "high_raw", "low_raw", "close_raw"]] <= 0).any(axis=1)
            | (numeric["high_raw"] + EPS < numeric[["open_raw", "close_raw", "low_raw"]].max(axis=1))
            | (numeric["low_raw"] - EPS > numeric[["open_raw", "close_raw", "high_raw"]].min(axis=1))
            | numeric["volume_raw"].isna()
            | (numeric["volume_raw"] < 0)
        )
        invalid_count = int(invalid_ohlc.sum())
    else:
        invalid_count = 0
    check("valid_raw_ohlcv", invalid_count == 0, invalid_count, "== 0")
    out_of_window = 0
    if not raw.empty:
        out_of_window = int(
            ((raw["date"].dt.date < RAW_START) | (raw["date"].dt.date >= RAW_END_EXCLUSIVE)).sum()
        )
    check("raw_date_window", out_of_window == 0, out_of_window, "== 0")
    if not splits.empty:
        invalid_splits = int(
            (~np.isfinite(splits["split_ratio"]) | (splits["split_ratio"] <= 0)).sum()
        )
        duplicate_splits = int(splits.duplicated(["security_code", "split_date", "split_ratio"]).sum())
        split_outside_universe = len(set(splits["security_code"]) - set(frozen_codes))
    else:
        invalid_splits = duplicate_splits = split_outside_universe = 0
    check("valid_split_ratios", invalid_splits == 0, invalid_splits, "== 0")
    check("unique_split_events", duplicate_splits == 0, duplicate_splits, "== 0")
    check("split_universe_isolation", split_outside_universe == 0, split_outside_universe, "== 0")

    coverage = pd.DataFrame(columns=["date", "price_codes", "coverage_vs_peak"])
    calendar: list[pd.Timestamp] = []
    if not raw.empty:
        daily = raw.groupby("date")["security_code"].nunique().sort_index()
        peak = int(daily.max())
        calendar = list(daily[daily >= peak * 0.50].index)
        coverage = daily.rename("price_codes").reset_index()
        coverage["coverage_vs_peak"] = coverage["price_codes"] / peak
        coverage["is_consensus_session"] = coverage["date"].isin(calendar)
        target_coverage = coverage[
            coverage["is_consensus_session"]
            & (coverage["date"].dt.date >= EVAL_START)
            & (coverage["date"].dt.date <= LAST_COMPLETE_SESSION_CAP)
        ]
        min_target_coverage = (
            float(target_coverage["coverage_vs_peak"].min()) if not target_coverage.empty else 0.0
        )
        last_session = max(calendar).date() if calendar else None
        eval_sessions = sum(EVAL_START <= day.date() <= LAST_COMPLETE_SESSION_CAP for day in calendar)
    else:
        peak = 0
        min_target_coverage = 0.0
        last_session = None
        eval_sessions = 0
    check("consensus_calendar_sessions", len(calendar) >= 80, len(calendar), ">= 80")
    check("evaluation_sessions", eval_sessions >= 55, eval_sessions, ">= 55")
    check(
        "last_complete_session",
        last_session == LAST_COMPLETE_SESSION_CAP,
        str(last_session),
        LAST_COMPLETE_SESSION_CAP.isoformat(),
    )
    check("daily_coverage_floor", min_target_coverage >= 0.97, min_target_coverage, ">= 0.97")

    adjustment_checks_pass = False
    adjusted_hash = ""
    if not raw.empty and invalid_count == 0 and duplicate_splits == 0 and invalid_splits == 0:
        adjusted = normalize_split_only(raw, splits)
        compare_columns = [
            "security_code",
            "date",
            "open_adj",
            "high_adj",
            "low_adj",
            "close_adj",
            "volume_adj",
            "split_future_factor",
        ]
        adjusted_hash = frame_hash(adjusted, compare_columns)
        shuffled = raw.sample(frac=1, random_state=20260908).reset_index(drop=True)
        shuffled_adjusted = normalize_split_only(shuffled, splits)
        row_order_hash = frame_hash(shuffled_adjusted, compare_columns)
        isolated = pd.concat(
            [normalize_split_only(group, splits[splits["security_code"] == code])
             for code, group in raw.groupby("security_code", sort=False)],
            ignore_index=True,
        )
        isolated_hash = frame_hash(isolated, compare_columns)
        row_order_ok = adjusted_hash == row_order_hash
        group_isolation_ok = adjusted_hash == isolated_hash
        adjustment_checks_pass = row_order_ok and group_isolation_ok
        check("row_order_invariance", row_order_ok, row_order_hash, adjusted_hash)
        check("adjustment_group_isolation", group_isolation_ok, isolated_hash, adjusted_hash)
    else:
        check("row_order_invariance", False, "not run", "hash equality")
        check("adjustment_group_isolation", False, "not run", "hash equality")

    gate_pass = all(item["passed"] for item in checks)
    raw.to_csv(output / "validated_raw_ohlcv.csv.gz", index=False)
    attempts.to_csv(output / "validated_attempts.csv", index=False)
    splits.to_csv(output / "validated_split_events.csv", index=False)
    coverage.to_csv(output / "coverage_by_date.csv", index=False)
    pd.DataFrame(checks).to_csv(output / "quality_checks.csv", index=False)
    report = {
        "schema_version": 1,
        "gate_pass": gate_pass,
        "outcome_scoring_performed": False,
        "frozen_universe_codes": UNIVERSE_SIZE,
        "attempted_codes": len(attempts),
        "price_codes": len(raw_codes),
        "price_rows": len(raw),
        "status_counts": status_counts,
        "split_events": len(splits),
        "peak_daily_codes": peak,
        "consensus_sessions": len(calendar),
        "evaluation_sessions": eval_sessions,
        "min_evaluation_daily_coverage_vs_peak": min_target_coverage,
        "last_complete_session": str(last_session),
        "adjusted_frame_hash": adjusted_hash,
        "checks_failed": [item["check"] for item in checks if not item["passed"]],
        "completed_at_utc": utc_now(),
    }
    write_json(output / "quality_report.json", report)
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as stream:
            stream.write(f"gate_pass={'true' if gate_pass else 'false'}\n")
    print(json.dumps(json_safe(report), sort_keys=True, allow_nan=False))
    return gate_pass


def exact_session_features(adjusted: pd.DataFrame, calendar: list[pd.Timestamp]) -> pd.DataFrame:
    data = adjusted.copy().sort_values(["security_code", "date"], kind="stable").reset_index(drop=True)
    session_index = {pd.Timestamp(day): index for index, day in enumerate(calendar)}
    data["session_index"] = pd.to_datetime(data["date"]).map(session_index)
    group = data.groupby("security_code", sort=False)
    previous_index = group["session_index"].shift(1)
    previous_close = group["close_adj"].shift(1)
    data["r1"] = np.where(
        data["session_index"] - previous_index == 1,
        data["close_adj"] / previous_close - 1,
        np.nan,
    )
    close_20 = group["close_adj"].shift(20)
    index_20 = group["session_index"].shift(20)
    data["mom20"] = np.where(
        data["session_index"] - index_20 == 20,
        data["close_adj"] / close_20 - 1,
        np.nan,
    )
    data["volume_median_previous20"] = group["volume_adj"].transform(
        lambda values: values.shift(1).rolling(20, min_periods=10).median()
    )
    data["volume_ratio20"] = data["volume_adj"] / data["volume_median_previous20"]
    data["rvol20"] = data.groupby("security_code", sort=False)["r1"].transform(
        lambda values: values.rolling(20, min_periods=10).std()
    )
    turnover = data["close_adj"] * data["volume_adj"]
    data["turnover20"] = turnover.groupby(data["security_code"], sort=False).transform(
        lambda values: values.rolling(20, min_periods=10).median()
    )
    eligible = data[["mom20", "volume_ratio20", "rvol20", "turnover20"]].replace(
        [np.inf, -np.inf], np.nan
    ).notna().all(axis=1)
    data["eligible"] = eligible
    for source, output in (
        ("mom20", "mom_pct"),
        ("volume_ratio20", "volume_ratio_pct"),
        ("rvol20", "rvol_pct"),
        ("turnover20", "turnover_pct"),
    ):
        data[output] = np.nan
        data.loc[eligible, output] = data.loc[eligible].groupby("date")[source].rank(
            pct=True, method="average"
        )
    data["vol_q"] = np.ceil(data["rvol_pct"] * 5).clip(1, 5)
    data["liq_q"] = np.ceil(data["turnover_pct"] * 5).clip(1, 5)
    data["event_spike_v1"] = (
        eligible & (data["mom_pct"] > 0.80) & (data["volume_ratio_pct"] > 0.80)
    )
    data["pullback_v1"] = data["event_spike_v1"] & data["r1"].between(-0.05, 0.0)
    data["tail_spike_v2"] = data["pullback_v1"] & (data["mom_pct"] >= 0.98)
    return data


def add_exact_five_session_outcomes(data: pd.DataFrame) -> pd.DataFrame:
    result = data.copy()
    group = result.groupby("security_code", sort=False)
    entry = group["open_adj"].shift(-1).to_numpy(float)
    close_day5 = group["close_adj"].shift(-5).to_numpy(float)
    max_close = np.full(len(result), -np.inf)
    max_high = np.full(len(result), -np.inf)
    min_low = np.full(len(result), np.inf)
    valid = np.isfinite(entry) & np.isfinite(close_day5)
    current_index = result["session_index"].to_numpy(float)
    for offset in range(1, 6):
        future_index = group["session_index"].shift(-offset).to_numpy(float)
        valid &= future_index == current_index + offset
        max_close = np.maximum(max_close, group["close_adj"].shift(-offset).to_numpy(float))
        max_high = np.maximum(max_high, group["high_adj"].shift(-offset).to_numpy(float))
        min_low = np.minimum(min_low, group["low_adj"].shift(-offset).to_numpy(float))
    valid &= np.isfinite(max_close) & np.isfinite(max_high) & np.isfinite(min_low)
    result["valid_outcome5"] = valid
    result["entry_open_t1"] = np.where(valid, entry, np.nan)
    result["ret_day5"] = np.where(valid, close_day5 / entry - 1, np.nan)
    result["hit10_close5"] = np.where(valid, max_close / entry >= 1.10 - EPS, np.nan)
    result["tail20_day5"] = np.where(valid, close_day5 / entry - 1 >= 0.20 - EPS, np.nan)
    result["mfe_close5"] = np.where(valid, max_close / entry - 1, np.nan)
    result["mfe_high5"] = np.where(valid, max_high / entry - 1, np.nan)
    result["mae_low5"] = np.where(valid, min_low / entry - 1, np.nan)
    return result


def trimmed_mean(values: pd.Series, fraction: float) -> float:
    array = np.sort(values.dropna().to_numpy(float))
    if len(array) == 0:
        return float("nan")
    cut = int(math.floor(len(array) * fraction))
    if cut == 0:
        return float(array.mean())
    return float(array[cut:-cut].mean()) if len(array) > cut * 2 else float("nan")


def huber_mean(values: pd.Series, tuning: float = 1.345) -> float:
    array = values.dropna().to_numpy(float)
    if len(array) == 0:
        return float("nan")
    location = float(np.median(array))
    mad = float(np.median(np.abs(array - location)))
    scale = max(1.4826 * mad, 1e-12)
    for _ in range(100):
        residual = (array - location) / scale
        weights = np.ones_like(residual)
        large = np.abs(residual) > tuning
        weights[large] = tuning / np.abs(residual[large])
        updated = float(np.sum(weights * array) / np.sum(weights))
        if abs(updated - location) < 1e-12:
            break
        location = updated
    return location


def wilson_interval(successes: int, trials: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if trials == 0:
        return float("nan"), float("nan")
    probability = successes / trials
    denominator = 1 + z * z / trials
    center = (probability + z * z / (2 * trials)) / denominator
    radius = z * math.sqrt(probability * (1 - probability) / trials + z * z / (4 * trials * trials)) / denominator
    return center - radius, center + radius


def cluster_bootstrap(signal_rows: pd.DataFrame, draws: int = 2000) -> pd.DataFrame:
    securities = signal_rows["security_code"].drop_duplicates().to_numpy()
    if len(securities) == 0:
        return pd.DataFrame(columns=["draw", "tail_rate", "parent_matched_tail", "lift_parent"])
    groups = {code: group for code, group in signal_rows.groupby("security_code", sort=False)}
    rng = np.random.default_rng(20260908)
    output: list[dict[str, float | int]] = []
    for draw in range(draws):
        sampled = rng.choice(securities, size=len(securities), replace=True)
        sample = pd.concat([groups[code] for code in sampled], ignore_index=True)
        signal_rate = float(sample["tail20_day5"].mean())
        parent_rate = float(sample["parent_tail20_day5"].mean())
        output.append(
            {
                "draw": draw,
                "tail_rate": signal_rate,
                "parent_matched_tail": parent_rate,
                "lift_parent": signal_rate / parent_rate if parent_rate > 0 else np.nan,
            }
        )
    return pd.DataFrame(output)


def safe_ratio(numerator: float, denominator: float) -> float:
    if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator == 0:
        return float("nan")
    return numerator / denominator


def evaluate(input_dir: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    quality = json.loads((input_dir / "quality_report.json").read_text())
    if not quality.get("gate_pass") or quality.get("outcome_scoring_performed"):
        raise RuntimeError("frozen evaluator requires a passed, outcome-blind quality gate")
    raw = pd.read_csv(input_dir / "validated_raw_ohlcv.csv.gz", dtype={"security_code": str})
    splits = pd.read_csv(input_dir / "validated_split_events.csv", dtype={"security_code": str})
    coverage = pd.read_csv(input_dir / "coverage_by_date.csv")
    raw["security_code"] = raw["security_code"].astype(str)
    raw["date"] = pd.to_datetime(raw["date"]).dt.normalize()
    if not splits.empty:
        splits["security_code"] = splits["security_code"].astype(str)
        splits["split_date"] = pd.to_datetime(splits["split_date"]).dt.normalize()
    calendar = sorted(
        pd.to_datetime(coverage.loc[coverage["is_consensus_session"].astype(str).str.lower() == "true", "date"]).dt.normalize().unique()
    )
    adjusted = normalize_split_only(raw, splits)
    data = exact_session_features(adjusted, [pd.Timestamp(day) for day in calendar])
    data = add_exact_five_session_outcomes(data)
    base = (
        data["eligible"]
        & data["valid_outcome5"]
        & (data["date"].dt.date >= EVAL_START)
        & (data["date"].dt.date <= LAST_COMPLETE_SESSION_CAP)
    )
    signal = base & data["tail_spike_v2"]
    broad = base & ~data["tail_spike_v2"]
    parent = base & data["pullback_v1"] & ~data["tail_spike_v2"]
    keys = ["date", "vol_q", "liq_q"]
    outcome_columns = [
        "tail20_day5",
        "hit10_close5",
        "ret_day5",
        "mfe_close5",
        "mfe_high5",
        "mae_low5",
    ]
    broad_cells = (
        data.loc[broad, keys + outcome_columns]
        .groupby(keys, observed=True)
        .mean()
        .add_prefix("broad_")
        .reset_index()
    )
    parent_cells = (
        data.loc[parent, keys + outcome_columns]
        .groupby(keys, observed=True)
        .mean()
        .add_prefix("parent_")
        .reset_index()
    )
    signal_columns = keys + [
        "security_code",
        "ticker",
        "mom20",
        "mom_pct",
        "volume_ratio20",
        "volume_ratio_pct",
        "r1",
        "entry_open_t1",
    ] + outcome_columns
    signal_rows = (
        data.loc[signal, signal_columns]
        .merge(broad_cells, on=keys, how="left", validate="many_to_one")
        .merge(parent_cells, on=keys, how="left", validate="many_to_one")
    )
    matched = signal_rows.dropna(subset=["broad_tail20_day5", "parent_tail20_day5"]).copy()
    metric_rows: list[dict[str, Any]] = []
    for metric in outcome_columns:
        signal_value = float(matched[metric].mean())
        broad_value = float(matched[f"broad_{metric}"].mean())
        parent_value = float(matched[f"parent_{metric}"].mean())
        metric_rows.append(
            {
                "candidate": "TAIL_SPIKE_V2",
                "metric": metric,
                "n_signal_raw": len(signal_rows),
                "n_matched": len(matched),
                "signal": signal_value,
                "broad_matched": broad_value,
                "parent_matched": parent_value,
                "excess_broad": signal_value - broad_value,
                "excess_parent": signal_value - parent_value,
                "lift_broad": safe_ratio(signal_value, broad_value),
                "lift_parent": safe_ratio(signal_value, parent_value),
            }
        )
    metrics = pd.DataFrame(metric_rows)
    robust = pd.DataFrame(
        [
            {"metric": "n", "value": len(matched)},
            {"metric": "mean_ret5", "value": float(matched["ret_day5"].mean())},
            {"metric": "median_ret5", "value": float(matched["ret_day5"].median())},
            {"metric": "trimmed_mean_1pct", "value": trimmed_mean(matched["ret_day5"], 0.01)},
            {"metric": "trimmed_mean_5pct", "value": trimmed_mean(matched["ret_day5"], 0.05)},
            {"metric": "huber_mean", "value": huber_mean(matched["ret_day5"])},
            {"metric": "p_ret5_gt_0", "value": float((matched["ret_day5"] > 0).mean())},
            {"metric": "p_ret5_ge_5pct", "value": float((matched["ret_day5"] >= 0.05 - EPS).mean())},
            {"metric": "p_ret5_ge_10pct", "value": float((matched["ret_day5"] >= 0.10 - EPS).mean())},
            {"metric": "p_ret5_ge_20pct", "value": float((matched["ret_day5"] >= 0.20 - EPS).mean())},
            {"metric": "p_ret5_le_minus5pct", "value": float((matched["ret_day5"] <= -0.05 + EPS).mean())},
            {"metric": "p_ret5_le_minus10pct", "value": float((matched["ret_day5"] <= -0.10 + EPS).mean())},
            {"metric": "cvar_lower_5pct", "value": float(matched.loc[matched["ret_day5"] <= matched["ret_day5"].quantile(0.05), "ret_day5"].mean())},
            {"metric": "tail_ratio_p95_abs_p05", "value": float(matched["ret_day5"].quantile(0.95) / abs(matched["ret_day5"].quantile(0.05)))},
        ]
    )
    tail_successes = int(matched["tail20_day5"].sum())
    tail_trials = len(matched)
    wilson_low, wilson_high = wilson_interval(tail_successes, tail_trials)
    bootstrap = cluster_bootstrap(matched, draws=2000)
    bootstrap_summary = {
        column: {
            "p025": float(bootstrap[column].quantile(0.025)),
            "p50": float(bootstrap[column].quantile(0.50)),
            "p975": float(bootstrap[column].quantile(0.975)),
        }
        for column in ("tail_rate", "parent_matched_tail", "lift_parent")
    }
    temporal = (
        matched.assign(month=matched["date"].dt.to_period("M").astype(str))
        .groupby("month", observed=True)
        .agg(
            n=("tail20_day5", "size"),
            tail_events=("tail20_day5", "sum"),
            tail_rate=("tail20_day5", "mean"),
            parent_matched_tail=("parent_tail20_day5", "mean"),
            mean_ret5=("ret_day5", "mean"),
            median_ret5=("ret_day5", "median"),
        )
        .reset_index()
    )
    temporal["tail_lift_parent"] = temporal["tail_rate"] / temporal["parent_matched_tail"]
    summary = {
        "status": "PROVISIONAL_NEAR_LIVE_OOS_FROZEN_UNION_UNIVERSE",
        "candidate": "TAIL_SPIKE_V2",
        "frozen_rule": "PULLBACK_V1 AND mom_pct >= 0.98",
        "threshold_retuned": False,
        "universe_codes": UNIVERSE_SIZE,
        "universe_sha256": UNIVERSE_CSV_SHA256,
        "price_codes": int(raw["security_code"].nunique()),
        "price_rows": len(raw),
        "evaluation_start": EVAL_START.isoformat(),
        "last_complete_session": LAST_COMPLETE_SESSION_CAP.isoformat(),
        "last_signal_date_with_exact_5d_outcome": str(data.loc[base, "date"].max().date()),
        "eligible_rows": int(base.sum()),
        "signal_rows_raw": len(signal_rows),
        "signal_rows_matched": len(matched),
        "tail20_events": tail_successes,
        "tail20_rate": tail_successes / tail_trials if tail_trials else None,
        "tail20_wilson_95": [wilson_low, wilson_high],
        "parent_matched_tail20": float(matched["parent_tail20_day5"].mean()),
        "tail20_lift_vs_parent": safe_ratio(
            float(matched["tail20_day5"].mean()),
            float(matched["parent_tail20_day5"].mean()),
        ),
        "broad_matched_tail20": float(matched["broad_tail20_day5"].mean()),
        "tail20_lift_vs_broad": safe_ratio(
            float(matched["tail20_day5"].mean()),
            float(matched["broad_tail20_day5"].mean()),
        ),
        "cluster_bootstrap_2000": bootstrap_summary,
        "evaluated_at_utc": utc_now(),
    }
    signal_rows.to_csv(output / "tail_spike_v2_signal_rows.csv", index=False)
    metrics.to_csv(output / "tail_spike_v2_metrics.csv", index=False)
    robust.to_csv(output / "tail_spike_v2_robust_returns.csv", index=False)
    temporal.to_csv(output / "tail_spike_v2_temporal.csv", index=False)
    bootstrap.to_csv(output / "tail_spike_v2_cluster_bootstrap.csv", index=False)
    write_json(output / "near_live_summary.json", summary)
    print(json.dumps(json_safe(summary), sort_keys=True, allow_nan=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    acquire_parser = subparsers.add_parser("acquire")
    acquire_parser.add_argument("--root", type=Path, default=Path("."))
    acquire_parser.add_argument("--output", type=Path, required=True)
    acquire_parser.add_argument("--shard-id", type=int, required=True)
    acquire_parser.add_argument("--shard-count", type=int, default=SHARD_COUNT)
    quality_parser = subparsers.add_parser("quality")
    quality_parser.add_argument("--root", type=Path, default=Path("."))
    quality_parser.add_argument("--input", type=Path, required=True)
    quality_parser.add_argument("--output", type=Path, required=True)
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--input", type=Path, required=True)
    evaluate_parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.mode == "acquire":
        acquire(args.root, args.output, args.shard_id, args.shard_count)
    elif args.mode == "quality":
        quality_gate(args.root, args.input, args.output)
    elif args.mode == "evaluate":
        evaluate(args.input, args.output)


if __name__ == "__main__":
    main()
