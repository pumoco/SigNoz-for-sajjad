from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import verify_signoz


def test_headers_from_environment_are_parsed_without_becoming_output() -> None:
    headers = verify_signoz.headers_from_environment(
        {
            "SIGNOZ_VERIFY_HEADERS_JSON": json.dumps(
                {"X-Api-Key": "super-secret", "X-Tenant": "tenant-a"}
            ),
            "SIGNOZ_VERIFY_BEARER_TOKEN": "bearer-secret",
        }
    )

    assert headers == {
        "X-Api-Key": "super-secret",
        "X-Tenant": "tenant-a",
        "Authorization": "Bearer bearer-secret",
    }
    rendered = json.dumps(verify_signoz.redact_output({"headers": headers}))
    assert "super-secret" not in rendered
    assert "bearer-secret" not in rendered
    assert "tenant-a" in rendered


def test_synthetic_payloads_carry_one_known_correlation_id() -> None:
    payloads, identifiers = verify_signoz.synthetic_payloads("corr-123")

    assert identifiers["correlation_id"] == "corr-123"
    assert payloads["traces"]["resourceSpans"][0]["resource"]["attributes"][-1]["value"]["stringValue"] == "corr-123"
    assert payloads["logs"]["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["attributes"][-1]["value"]["stringValue"] == "corr-123"
    assert payloads["metrics"]["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]["description"] == "synthetic correlation probe"


def test_query_evidence_requires_correlation_id_in_real_response() -> None:
    assert verify_signoz.contains_correlation_evidence('{"data":[{"correlation_id":"corr-123"}]}', "corr-123")
    assert not verify_signoz.contains_correlation_evidence('{"data":[]}', "corr-123")


def test_readiness_and_round_trip_are_distinct() -> None:
    report = verify_signoz.build_report(
        {
            "collector": {"status": 200},
            "query": {"status": 200},
            "backend": {"status": 200},
            "clickhouse": {"status": 200},
        },
        round_trip={"status": "receipt_verified"},
    )

    assert report["readiness"]["status"] == "ready"
    assert report["round_trip"]["status"] == "receipt_verified"
    assert report["readiness"]["status"] != report["round_trip"]["status"]


def test_failed_readiness_is_not_ready_even_when_round_trip_receipt_succeeds() -> None:
    report = verify_signoz.build_report(
        {
            "collector": {"status": 200},
            "query": {"status": 503},
            "backend": {"status": 200},
            "clickhouse": {"status": 200},
        },
        round_trip={"status": "receipt_verified"},
    )

    assert report["readiness"]["status"] == "not_ready"
    assert report["round_trip"]["status"] == "receipt_verified"
    assert report["ok"] is False
