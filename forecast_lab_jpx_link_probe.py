from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen


PAGES = [
    "https://www.jpx.co.jp/markets/statistics-equities/price/index.html",
    "https://www.jpx.co.jp/markets/statistics-equities/price/00-archives-01.html",
    "https://www.jpx.co.jp/english/markets/statistics-equities/daily/index.html",
]


def inspect(page: str) -> dict[str, object]:
    request = Request(page, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html,*/*"})
    with urlopen(request, timeout=60) as response:
        body = response.read()
        content_type = response.headers.get("content-type")
        final_url = response.url
    text = body.decode("utf-8", errors="replace")
    hrefs = [urljoin(final_url, unescape(value)) for value in re.findall(r'href=["\']([^"\']+)', text)]
    relevant = sorted(
        {
            href
            for href in hrefs
            if any(token in href.lower() for token in ("-att/", ".csv", ".xls", ".xlsx", ".pdf"))
        }
    )
    return {
        "page": page,
        "final_url": final_url,
        "status": 200,
        "content_type": content_type,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "relevant_links": relevant,
    }


def main() -> None:
    output = Path("provider_probe")
    output.mkdir(parents=True, exist_ok=True)
    payload = {
        "purpose": "outcome-blind official JPX route discovery",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "pages": [inspect(page) for page in PAGES],
    }
    (output / "jpx_link_probe.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
