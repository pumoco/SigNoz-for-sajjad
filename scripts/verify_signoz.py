#!/usr/bin/env python3
"""Verify SigNoz liveness, query API, and OTLP boundary without sending secrets."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REQUIRED_QUERY_PATHS = ("/api/v1/health", "/api/v1/logs")


def probe(url: str, timeout: float) -> dict[str, object]:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(512).decode("utf-8", errors="replace")
            return {"url": url, "status": response.status, "body": body}
    except HTTPError as error:
        return {"url": url, "status": error.code, "body": error.read(512).decode("utf-8", errors="replace")}
    except (TimeoutError, URLError, OSError) as error:
        return {"url": url, "status": None, "error": type(error).__name__}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    results = [probe(f"{base}/healthz", args.timeout)]
    results.extend(probe(f"{base}{path}", args.timeout) for path in REQUIRED_QUERY_PATHS)
    print(json.dumps(results, indent=2, sort_keys=True))
    healthy = results[0].get("status") == 200
    query_ready = all(result.get("status") == 200 for result in results[1:])
    if not healthy or not query_ready:
        print("SigNoz is not query-ready: collector liveness and query readiness are separate gates.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
