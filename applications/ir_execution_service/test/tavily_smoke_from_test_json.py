"""
Smoke test: same Tavily params as applications/ir_execution_service/test/test.json
(plugin_BCvUb.configs.tool). Uses stdlib only.
"""
from __future__ import annotations

import json
import ssl
import sys
import urllib.error
import urllib.request

# Copied from test.json → plugin_BCvUb.configs.tool
URL = "https://api.tavily.com/search"
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": "Bearer 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",
}
# Body matches tool params: query (runtime), search_depth default "advanced"
BODY = {
    "query": "Python asyncio best practices",
    "search_depth": "advanced",
}


def main() -> int:
    data = json.dumps(BODY).encode("utf-8")
    req = urllib.request.Request(URL, data=data, headers=HEADERS, method="POST")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print("HTTPError", e.code, e.reason)
        print("body:", body[:2000])
        return 1
    except urllib.error.URLError as e:
        print("URLError:", e.reason)
        return 1

    print("HTTP status:", status)
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        print("Non-JSON body (first 500 chars):", raw[:500])
        return 1

    print("Top-level keys:", sorted(obj.keys()))
    results = obj.get("results")
    if isinstance(results, list):
        print("results count:", len(results))
        for i, r in enumerate(results[:3]):
            title = (r or {}).get("title", "")
            url_ = (r or {}).get("url", "")
            print(f"  [{i}] {title!r} -> {url_!r}")
    else:
        print("results field:", type(results), results)

    err = obj.get("error") or obj.get("detail")
    if err:
        print("API error field:", err)

    return 0 if results else 2


if __name__ == "__main__":
    sys.exit(main())
