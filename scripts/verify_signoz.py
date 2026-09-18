#!/usr/bin/env python3
"""Verify collector liveness separately from SigNoZ query readiness.

The optional OTLP probe sends one short-lived readiness log. Searchability is
only reported when the caller supplies a real Query Service request and it
returns a matching result; collector /healthz alone never passes that gate.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request(url: str, method: str = "GET", body: object | None = None, timeout: float = 10) -> dict[str, object]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    try:
        with urlopen(Request(url, data=data, headers=headers, method=method), timeout=timeout) as response:
            return {"url": url, "status": response.status, "body": response.read(4096).decode("utf-8", "replace")}
    except HTTPError as error:
        return {"url": url, "status": error.code, "body": error.read(4096).decode("utf-8", "replace")}
    except (TimeoutError, URLError, OSError) as error:
        return {"url": url, "status": None, "error": type(error).__name__}


def send_readiness_log(collector: str, service_name: str, timeout: float) -> tuple[dict[str, object], str]:
    now = time.time_ns()
    trace_id = uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]
    body = {"resourceLogs": [{"resource": {"attributes": [
        {"key": "service.name", "value": {"stringValue": service_name}},
        {"key": "service.version", "value": {"stringValue": "readiness"}},
        {"key": "deployment.environment", "value": {"stringValue": "verification"}},
        {"key": "request_id", "value": {"stringValue": trace_id}},
        {"key": "task.id", "value": {"stringValue": "signoz-readiness"}},
    ]}, "scopeLogs": [{"logRecords": [{
        "timeUnixNano": str(now), "severityText": "INFO", "body": {"stringValue": "signoz-readiness-test"},
        "traceId": trace_id, "spanId": span_id,
    }]}]}]}
    return request(f"{collector.rstrip('/')}/v1/logs", "POST", body, timeout), trace_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collector", required=True, help="Collector base URL, not the Query Service")
    parser.add_argument("--query", required=True, help="SigNoZ Query Service base URL")
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--send-readiness-log", action="store_true")
    parser.add_argument("--query-path", default="/api/v1/health")
    parser.add_argument("--query-payload", help="JSON file for an actual telemetry search request")
    args = parser.parse_args()
    collector = args.collector.rstrip("/")
    query = args.query.rstrip("/")
    results: dict[str, object] = {
        "collector_liveness": request(f"{collector}/healthz", timeout=args.timeout),
        "query_readiness": request(f"{query}/api/v1/health", timeout=args.timeout),
    }
    if args.send_readiness_log:
        results["otlp_log"] = (sent := send_readiness_log(collector, "signoz-readiness-test", args.timeout))[0]
        results["readiness_request_id"] = sent[1]
    if args.query_payload:
        with open(args.query_payload, encoding="utf-8") as payload_file:
            payload = json.load(payload_file)
        results["telemetry_search"] = request(f"{query}{args.query_path}", "POST", payload, args.timeout)
    print(json.dumps(results, indent=2, sort_keys=True))
    collector_ok = isinstance(results["collector_liveness"], dict) and results["collector_liveness"].get("status") == 200
    query_ok = isinstance(results["query_readiness"], dict) and results["query_readiness"].get("status") == 200
    if not collector_ok or not query_ok:
        print("NOT READY: collector liveness and Query Service readiness are separate gates.", file=sys.stderr)
        return 2
    if "telemetry_search" in results and (not isinstance(results["telemetry_search"], dict) or results["telemetry_search"].get("status") not in (200, 201)):
        print("NOT SEARCH-VERIFIED: the supplied Query Service search failed.", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
