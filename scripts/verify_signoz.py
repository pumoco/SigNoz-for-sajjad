#!/usr/bin/env python3
"""Run separate, fail-closed checks for the collector and SigNoz stack."""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def probe(url: str, timeout: float) -> dict[str, object]:
    try:
        with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=timeout) as response:
            return {"url": url, "status": response.status, "body": response.read(4096).decode("utf-8", "replace")}
    except HTTPError as error:
        return {"url": url, "status": error.code, "body": error.read(4096).decode("utf-8", "replace")}
    except (TimeoutError, URLError, OSError) as error:
        return {"url": url, "status": None, "error": type(error).__name__}


def post_json(url: str, payload: object, timeout: float) -> dict[str, object]:
    try:
        request = Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=timeout) as response:
            return {"url": url, "status": response.status, "body": response.read(4096).decode("utf-8", "replace")}
    except HTTPError as error:
        return {"url": url, "status": error.code, "body": error.read(4096).decode("utf-8", "replace")}
    except (TimeoutError, URLError, OSError) as error:
        return {"url": url, "status": None, "error": type(error).__name__}


def attribute(key: str, value: str) -> dict[str, object]:
    return {"key": key, "value": {"stringValue": value}}


def readiness_ids() -> tuple[str, str]:
    return uuid.uuid4().hex, uuid.uuid4().hex[:16]


def send_otlp(collector: str, timeout: float) -> tuple[dict[str, object], dict[str, str]]:
    trace_id, span_id = readiness_ids()
    resource = {"attributes": [
        attribute("service.name", "signoz-readiness-test"),
        attribute("service.version", "readiness"),
        attribute("deployment.environment", "verification"),
        attribute("request_id", trace_id),
        attribute("task.id", "signoz-readiness"),
    ]}
    timestamp = str(time.time_ns())
    logs = {"resourceLogs": [{"resource": resource, "scopeLogs": [{"logRecords": [{
        "timeUnixNano": timestamp, "severityText": "INFO",
        "body": {"stringValue": "signoz-readiness-test"}, "traceId": trace_id, "spanId": span_id,
    }]}]}]}
    traces = {"resourceSpans": [{"resource": resource, "scopeSpans": [{"spans": [{
        "traceId": trace_id, "spanId": span_id, "name": "signoz-readiness-test",
        "kind": 1, "startTimeUnixNano": timestamp, "endTimeUnixNano": str(time.time_ns()),
    }]}]}]}
    metrics = {"resourceMetrics": [{"resource": resource, "scopeMetrics": [{"metrics": [{
        "name": "signoz_readiness_test", "unit": "1",
        "gauge": {"dataPoints": [{"asDouble": 1, "timeUnixNano": str(time.time_ns())}]},
    }]}]}]}
    results = {
        "logs": post_json(f"{collector}/v1/logs", logs, timeout),
        "traces": post_json(f"{collector}/v1/traces", traces, timeout),
        "metrics": post_json(f"{collector}/v1/metrics", metrics, timeout),
    }
    return results, {"trace_id": trace_id, "span_id": span_id}


def read_payload(path: str) -> object:
    with Path(path).open(encoding="utf-8") as payload_file:
        return json.load(payload_file)


def successful(result: object, accepted: tuple[int, ...] = (200, 201, 202, 204)) -> bool:
    return isinstance(result, dict) and result.get("status") in accepted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collector", required=True, help="collector base URL or private host")
    parser.add_argument("--query", required=True, help="public/internal SigNoz Query Service base URL")
    parser.add_argument("--backend", help="internal ingester base URL, for its health endpoint")
    parser.add_argument("--clickhouse", help="internal ClickHouse HTTP base URL")
    parser.add_argument("--query-health-path", default="/api/v1/health")
    parser.add_argument("--backend-health-path", default="/")
    parser.add_argument("--logs-payload", help="real Query Service search JSON payload")
    parser.add_argument("--traces-payload", help="real Query Service search JSON payload")
    parser.add_argument("--metrics-payload", help="real Query Service search JSON payload")
    parser.add_argument("--query-path", default="/api/v5/query_range")
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--send-otlp", action="store_true", help="send one log, trace, and metric through collector")
    args = parser.parse_args()

    collector = args.collector.rstrip("/")
    query = args.query.rstrip("/")
    results: dict[str, object] = {
        "collector_liveness": probe(f"{collector}/healthz", args.timeout),
        "signoz_query_readiness": probe(f"{query}{args.query_health_path}", args.timeout),
    }
    if args.backend:
        results["signoz_backend_readiness"] = probe(f"{args.backend.rstrip('/')}{args.backend_health_path}", args.timeout)
    if args.clickhouse:
        results["clickhouse_readiness"] = probe(f"{args.clickhouse.rstrip('/')}/ping", args.timeout)
    if args.send_otlp:
        results["end_to_end_otlp_ingestion"], identifiers = send_otlp(collector, args.timeout)
        results["correlation"] = identifiers

    search_payloads = {
        "searchable_logs": args.logs_payload,
        "searchable_traces": args.traces_payload,
        "searchable_metrics": args.metrics_payload,
    }
    for check, payload_path in search_payloads.items():
        if payload_path:
            results[check] = post_json(f"{query}{args.query_path}", read_payload(payload_path), args.timeout)

    print(json.dumps(results, indent=2, sort_keys=True))
    required = ["collector_liveness", "signoz_query_readiness"]
    if args.backend:
        required.append("signoz_backend_readiness")
    if args.clickhouse:
        required.append("clickhouse_readiness")
    if args.send_otlp:
        required.append("end_to_end_otlp_ingestion")
    required.extend(check for check, path in search_payloads.items() if path)
    failures: list[str] = []
    otlp_results = results.get("end_to_end_otlp_ingestion")
    if "end_to_end_otlp_ingestion" in required and (
        not isinstance(otlp_results, dict) or not all(successful(item) for item in otlp_results.values())
    ):
        failures.append("end_to_end_otlp_ingestion")
    failures.extend(
        check for check in required if check != "end_to_end_otlp_ingestion" and not successful(results.get(check))
    )
    if failures:
        print(f"NOT READY/VERIFIED: {', '.join(failures)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
