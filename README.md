# SigNoz-for-sajjad

Controlled observability plane for the PuMo services.

This repository contains the Runflare deployment contract for SigNoz and its
OpenTelemetry ingestion boundary. It is intentionally kept separate from
business traffic: telemetry must never sit inline between a service and an
exchange or API.

## Architecture

```text
crypto-engine / analysis-cms / MCP / workers
                 │ OTLP telemetry only
                 ▼
       SigNoz OpenTelemetry Collector
                 │
                 ▼
        SigNoz + ClickHouse storage
                 │
                 ▼
     controlled DSS/MCP observability queries
```

## Runflare deployment contract

Deploy this repository as a Docker service. The service must listen on the
platform-provided `PORT` value and bind to `0.0.0.0`.

Required environment variables:

- `PORT` — Runflare-assigned HTTP port; this deployment uses `8000`.
- `SIGNOZ_UI_BASE_URL` — public HTTPS URL for the SigNoz UI.
- `OTEL_EXPORTER_OTLP_ENDPOINT` — collector OTLP/HTTP endpoint; use the private
  service address when Runflare networking supports it.
- `SIGNOZ_ADMIN_USER` — optional operator identity; store the value in
  Runflare secrets, never in Git.
- `SIGNOZ_ADMIN_PASSWORD` — required operator secret; store only in Runflare
  secrets, never in Git.

Do not commit `.env` or credentials. Start from `.env.example`.

## Signals and safety

- OTLP/HTTP is the supported external ingestion boundary on port `4318`.
- OTLP/gRPC is available internally on port `4317` when the platform supports
  private service networking.
- The collector must batch and drop telemetry when downstream storage is
  unavailable rather than blocking business requests.
- Sensitive fields are filtered at the collector boundary. Applications must
  still redact credentials before export.
- The DSS/MCP query layer is read-only and bounded by time range, row count,
  service allow-list, and query timeout.
- No exchange orders, cancellations, withdrawals, balances, or execution
  mutations are implemented here.

## Local start

1. Copy `.env.example` to `.env` and set local values.
2. Run `docker compose config` to validate interpolation.
3. Run `docker compose up -d`.
4. Verify `http://localhost:8000/healthz` and the SigNoz UI.

Local defaults are for development only. Review resource limits before using a
small Runflare instance; SigNoz with ClickHouse is not a lightweight service.

## Planned integration phases

1. Deploy and verify SigNoz/ClickHouse health.
2. Send a synthetic telemetry event from each service.
3. Add Python and Node OpenTelemetry SDK exporters.
4. Add bounded read-only DSS/MCP query tools.
5. Run the five-minute observation cycle and correlate logs, traces, and
   metrics.

The repository does not claim a live deployment until the exact Runflare
commit, health response, public routes, and telemetry round-trip are verified.
