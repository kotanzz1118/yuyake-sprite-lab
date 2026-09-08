from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


URLS = [
    "https://static.stooq.com/db/h/d_jp_txt.zip",
    "https://static.stooq.pl/db/h/d_jp_txt.zip",
    "https://stooq.com/q/d/l/?s=7203.jp&d1=20260501&d2=20260907&i=d",
]


def probe(url: str) -> dict[str, object]:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "*/*",
            "Range": "bytes=0-65535",
        },
    )
    started = datetime.now(timezone.utc)
    try:
        with urlopen(request, timeout=60) as response:
            body = response.read(65536)
            headers = {key.lower(): value for key, value in response.headers.items()}
            status = response.status
            final_url = response.url
        return {
            "url": url,
            "status": status,
            "final_url": final_url,
            "content_type": headers.get("content-type"),
            "content_length": headers.get("content-length"),
            "content_range": headers.get("content-range"),
            "last_modified": headers.get("last-modified"),
            "etag": headers.get("etag"),
            "bytes_read": len(body),
            "prefix_hex": body[:16].hex(),
            "sample_sha256": hashlib.sha256(body).hexdigest(),
            "looks_like_zip": body.startswith(b"PK\\x03\\x04"),
            "looks_like_csv": body.lstrip().startswith((b"Date", b"<TICKER>")),
            "elapsed_seconds": (datetime.now(timezone.utc) - started).total_seconds(),
            "error": None,
        }
    except HTTPError as exc:
        body = exc.read(4096)
        return {
            "url": url,
            "status": exc.code,
            "final_url": exc.url,
            "content_type": exc.headers.get("content-type"),
            "content_length": exc.headers.get("content-length"),
            "bytes_read": len(body),
            "prefix_hex": body[:16].hex(),
            "sample_sha256": hashlib.sha256(body).hexdigest(),
            "looks_like_zip": body.startswith(b"PK\\x03\\x04"),
            "looks_like_csv": body.lstrip().startswith((b"Date", b"<TICKER>")),
            "elapsed_seconds": (datetime.now(timezone.utc) - started).total_seconds(),
            "error": f"HTTPError: {exc}",
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "url": url,
            "status": None,
            "bytes_read": 0,
            "looks_like_zip": False,
            "looks_like_csv": False,
            "elapsed_seconds": (datetime.now(timezone.utc) - started).total_seconds(),
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> None:
    output = Path("provider_probe")
    output.mkdir(parents=True, exist_ok=True)
    result = {
        "purpose": "outcome-blind provider-route probe",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "probes": [probe(url) for url in URLS],
    }
    (output / "provider_probe.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
