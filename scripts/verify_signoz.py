#!/usr/bin/env python3
"""Fail-closed readiness and telemetry round-trip checks for a SigNoz stack."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SUCCESS_STATUSES = tuple(range(200, 300))
SECRET_KEY = re.compile(r"(?:authorization|api[_-]?key|password|secret|token|private[_-]?key|credential|dsn)", re.I)
SECRET_VALUE = re.compile(r"(?i)(bearer\s+)[^\s,}]+|([?&](?:token|api[_-]?key|password|secret)=[^&\s]+)")


def redact_output(value: object, key: str = "") -> object:
    """Remove secret-shaped fields and values before output is serialized."""
    if SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(item_key): redact_output(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact_output(item, key) for item in value]
    if isinstance(value, str):
        return SECRET_VALUE.sub(lambda match: (match.group(1) or "") + "[REDACTED]", value)
    return value


def headers_from_environment(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    """Read optional request headers without exposing their values in reports."""
    values = dict(os.environ if environment is None else environment)
    headers: dict[str, str] = {}
    raw_headers = values.get("SIGNOZ_VERIFY_HEADERS_JSON")
    if raw_headers:
        parsed = json.loads(raw_headers)
        if not isinstance(parsed, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in parsed.items()):
            raise ValueError("SIGNOZ_VERIFY_HEADERS_JSON must be a JSON object of string pairs")
        headers.update(parsed)
    bearer = values.get("SIGNOZ_VERIFY_BEARER_TOKEN")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return headers


def request_json(url: str, timeout: float, headers: Mapping[str, str], payload: object | None = None) -> dict[str, object]:
    request_headers = {"Accept": "application/json", **headers}
    method = "GET"
    data = None
    if payload is not None:
        method = "POST"
        data = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(16384).decode("utf-8", "replace")
            return {"url": url, "status": response.status, "body": body}
    except HTTPError as error:
        return {"url": url, "status": error.code, "body": error.read(16384).decode("utf-8", "replace")}
    except (TimeoutError, URLError, OSError) as error:
        return {"url": url, "status": None, "error": type(error).__name__}


def probe(url: str, timeout: float, headers: Mapping[str, str] | None = None) -> dict[str, object]:
    return request_json(url, timeout, headers or {})


def attribute(key: str, value: str) -> dict[str, object]:
    return {"key": key, "value": {"stringValue": value}}


def synthetic_payloads(correlation_id: str) -> tuple[dict[str, object], dict[str, str]]:
    trace_id, span_id = uuid.uuid4().hex, uuid.uuid4().hex[:16]
    resource = {"attributes": [attribute("service.name", "signoz-verification-probe"), attribute("correlation_id", correlation_id)]}
    timestamp = str(time.time_ns())
    logs = {"resourceLogs": [{"resource": resource, "scopeLogs": [{"logRecords": [{
        "timeUnixNano": timestamp, "severityText": "INFO", "body": {"stringValue": "signoz synthetic verification probe"},
        "attributes": [attribute("correlation_id", correlation_id)], "traceId": trace_id, "spanId": span_id,
    }]}]}]}
    traces = {"resourceSpans": [{"resource": resource, "scopeSpans": [{"spans": [{
        "traceId": trace_id, "spanId": span_id, "name": "signoz-synthetic-verification-probe", "kind": 1,
        "startTimeUnixNano": timestamp, "endTimeUnixNano": str(time.time_ns()),
        "attributes": [attribute("correlation_id", correlation_id)],
    }]}]}]}
    metrics = {"resourceMetrics": [{"resource": resource, "scopeMetrics": [{"metrics": [{
        "name": "signoz_verification_probe", "description": "synthetic correlation probe", "unit": "1",
        "gauge": {"dataPoints": [{"asDouble": 1, "timeUnixNano": str(time.time_ns()), "attributes": [attribute("correlation_id", correlation_id)]}]},
    }]}]}]}
    return {"logs": logs, "traces": traces, "metrics": metrics}, {"correlation_id": correlation_id, "trace_id": trace_id, "span_id": span_id}


def send_otlp(collector: str, timeout: float, headers: Mapping[str, str], correlation_id: str) -> tuple[dict[str, object], dict[str, str]]:
    payloads, identifiers = synthetic_payloads(correlation_id)
    return {
        kind: request_json(f"{collector}/v1/{kind}", timeout, headers, payload)
        for kind, payload in payloads.items()
    }, identifiers


def read_payload(path: str) -> object:
    with Path(path).open(encoding="utf-8") as payload_file:
        return json.load(payload_file)


def replace_correlation_id(value: object, correlation_id: str) -> object:
    if isinstance(value, str):
        return value.replace("{{correlation_id}}", correlation_id)
    if isinstance(value, list):
        return [replace_correlation_id(item, correlation_id) for item in value]
    if isinstance(value, dict):
        return {key: replace_correlation_id(item, correlation_id) for key, item in value.items()}
    return value


def contains_correlation_evidence(body: str, correlation_id: str) -> bool:
    return correlation_id in body


def successful(result: object) -> bool:
    return isinstance(result, dict) and result.get("status") in SUCCESS_STATUSES


def build_report(readiness_results: Mapping[str, object], round_trip: Mapping[str, object]) -> dict[str, object]:
    readiness = {name: {"status": "ready" if successful(result) else "not_ready", "result": result} for name, result in readiness_results.items()}
    ready = bool(readiness) and all(item["status"] == "ready" for item in readiness.values())
    readiness_report = {"status": "ready" if ready else "not_ready", "checks": readiness}
    round_trip_report = dict(round_trip)
    ok = ready and round_trip_report.get("status") in {"not_requested", "receipt_verified", "query_verified", "query_evidence_verified"}
    return {"ok": ok, "readiness": readiness_report, "round_trip": round_trip_report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collector", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--backend", required=True, help="SigNoz ingestion backend health base URL")
    parser.add_argument("--clickhouse", required=True, help="ClickHouse HTTP base URL")
    parser.add_argument("--query-health-path", default="/api/v1/health")
    parser.add_argument("--backend-health-path", default="/")
    parser.add_argument("--logs-payload")
    parser.add_argument("--traces-payload")
    parser.add_argument("--metrics-payload")
    parser.add_argument("--query-path", default="/api/v5/query_range")
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--synthetic-probe", "--send-otlp", dest="synthetic_probe", action="store_true", help="emit trace, log, and metric with a correlation_id")
    args = parser.parse_args()
    try:
        headers = headers_from_environment()
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"invalid authentication header configuration: {type(error).__name__}", file=sys.stderr)
        return 2

    collector, query = args.collector.rstrip("/"), args.query.rstrip("/")
    readiness_results = {
        "collector": probe(f"{collector}/healthz", args.timeout, headers),
        "query": probe(f"{query}{args.query_health_path}", args.timeout, headers),
        "backend": probe(f"{args.backend.rstrip('/')}{args.backend_health_path}", args.timeout, headers),
        "clickhouse": probe(f"{args.clickhouse.rstrip('/')}/ping", args.timeout, headers),
    }
    identifiers: dict[str, str] = {}
    correlation_id = ""
    round_trip: dict[str, object] = {"status": "not_requested"}
    if args.synthetic_probe:
        correlation_id = f"signoz-verification-{uuid.uuid4().hex}"
        round_trip["receipt"], identifiers = send_otlp(collector, args.timeout, headers, correlation_id)
        if all(successful(item) for item in round_trip["receipt"].values()):
            round_trip["status"] = "receipt_verified"
        else:
            round_trip["status"] = "failed"
        round_trip["correlation_id"] = correlation_id

    payload_paths = {"logs": args.logs_payload, "traces": args.traces_payload, "metrics": args.metrics_payload}
    provided_payloads = {kind: path for kind, path in payload_paths.items() if path}
    if provided_payloads:
        if not args.synthetic_probe:
            correlation_id = ""
        query_results: dict[str, object] = {}
        for kind, path in provided_payloads.items():
            payload = read_payload(path)
            if args.synthetic_probe:
                payload = replace_correlation_id(payload, correlation_id)
            query_results[kind] = request_json(f"{query}{args.query_path}", args.timeout, headers, payload)
        round_trip["query_evidence"] = query_results
        if args.synthetic_probe:
            evidence_ok = all(
                isinstance(result, dict)
                and successful(result)
                and contains_correlation_evidence(str(result.get("body", "")), correlation_id)
                for result in query_results.values()
            )
            round_trip["status"] = "query_evidence_verified" if evidence_ok else "failed"
        else:
            round_trip["status"] = "query_verified" if all(successful(result) for result in query_results.values()) else "failed"
    report = build_report(readiness_results, round_trip)
    if identifiers:
        report["correlation"] = identifiers
    print(json.dumps(redact_output(report), indent=2, sort_keys=True))
    if not report["ok"]:
        print("NOT READY/VERIFIED", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
