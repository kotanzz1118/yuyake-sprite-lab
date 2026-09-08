from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen


BASE = "https://www.jpx.co.jp/english/markets/statistics-equities/daily/"
PAGES = [urljoin(BASE, "index.html")] + [
    urljoin(BASE, f"00-archives-{index:02d}.html") for index in range(1, 5)
]
START = date(2026, 5, 1)
END = date(2026, 9, 7)


def fetch(url: str) -> tuple[bytes, str, dict[str, str]]:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
    with urlopen(request, timeout=90) as response:
        return (
            response.read(),
            response.url,
            {key.lower(): value for key, value in response.headers.items()},
        )


def main() -> None:
    output = Path("provider_probe")
    output.mkdir(parents=True, exist_ok=True)
    discovered: dict[str, str] = {}
    page_records: list[dict[str, object]] = []
    for page in PAGES:
        body, final_url, headers = fetch(page)
        text = body.decode("utf-8", errors="replace")
        links = [urljoin(final_url, unescape(value)) for value in re.findall(r'href=["\']([^"\']+)', text)]
        stock_links = sorted({link for link in links if re.search(r"/stq_(\d{8})\.pdf(?:\?|$)", link)})
        for link in stock_links:
            match = re.search(r"/stq_(\d{8})\.pdf(?:\?|$)", link)
            assert match is not None
            day = datetime.strptime(match.group(1), "%Y%m%d").date()
            if START <= day <= END:
                key = day.isoformat()
                if key in discovered and discovered[key] != link:
                    raise RuntimeError(f"conflicting JPX stock reports for {key}")
                discovered[key] = link
        page_records.append(
            {
                "page": page,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "stock_report_links": len(stock_links),
            }
        )

    if not discovered:
        raise RuntimeError("no JPX stock daily reports discovered")
    latest_day = max(discovered)
    sample_body, sample_final_url, sample_headers = fetch(discovered[latest_day])
    if not sample_body.startswith(b"%PDF-"):
        raise RuntimeError("JPX stock report sample is not a PDF")
    sample_path = output / f"sample_stq_{latest_day.replace('-', '')}.pdf"
    sample_path.write_bytes(sample_body)
    payload = {
        "purpose": "outcome-blind official JPX daily-report route and format probe",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_window": [START.isoformat(), END.isoformat()],
        "page_records": page_records,
        "report_count": len(discovered),
        "reports": discovered,
        "sample": {
            "date": latest_day,
            "source_url": discovered[latest_day],
            "final_url": sample_final_url,
            "bytes": len(sample_body),
            "sha256": hashlib.sha256(sample_body).hexdigest(),
            "content_type": sample_headers.get("content-type"),
            "path": sample_path.name,
        },
    }
    (output / "jpx_daily_probe.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in payload.items() if key != "reports"}, indent=2))


if __name__ == "__main__":
    main()
