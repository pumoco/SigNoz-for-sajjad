# SigNoz observability stack

## Status

This repository preserves the existing OpenTelemetry Collector as the Runflare ingestion boundary. The official SigNoz Foundry Docker topology is in `deploy/compose.yaml`, pinned to SigNoz `v0.142.1`. The stack is not production-ready until Runflare deployment and an end-to-end searchable logs/traces/metrics test have passed.

## Architecture

Agents and microservices -> OTLP -> existing `otel-gateway` -> SigNoz ingester -> ClickHouse -> SigNoz Query Service -> frontend.

The existing gateway remains the only client-facing OTLP boundary. Its `otel/collector.config.yaml` keeps OTLP gRPC `4317`, OTLP HTTP `4318`, and health `8000 /healthz`, plus redaction and batching. Its exporter endpoint is supplied as `SIGNOZ_OTLP_HTTP_ENDPOINT`; in Runflare this must resolve to the private backend ingester (`http://signoz-ingester:4318`) over Cluster Network.

## Selected official release and images

Release: `v0.142.1` (official SigNoz source). Images:

- `signoz/signoz:v0.142.1` — Query Service/API and UI, container port `8080`.
- `signoz/signoz-otel-collector:v0.142.1` — official backend ingester and migrator, OTLP ports `4317`/`4318`.
- `clickhouse/clickhouse-server:25.12.5` — telemetry store, private ports `8123`/`9000`.
- `clickhouse/clickhouse-keeper:25.12.5` — ClickHouse coordination, private ports `9181`/`9234`.
- `postgres:16` — SigNoz metastore, private port `5432`.
- `otel/opentelemetry-collector-contrib:0.136.0` — existing gateway image; do not replace it as part of backend rollout.

The release topology and migration commands are based on the official Foundry Docker compose example, with only version pinning, secret interpolation, and the existing `/signoz-clickhouse` bind mount adapted here.

## Exact service topology

| Service | Container port | Runflare exposure | Visibility | Purpose |
|---|---:|---|---|---|
| existing `otel-gateway` | 8000, 4317, 4318 | keep existing service exposure | gateway boundary | health, OTLP gRPC/HTTP |
| `signoz-signoz-0` | 8080, 4320 | expose only frontend 8080 | public frontend only | real Query Service/API and UI |
| `ingester` | 4317, 4318 | Cluster Network only | private | backend OTLP ingestion to ClickHouse |
| `signoz-metastore-postgres-0` | 5432 | Cluster Network only | private | SigNoz SQL metastore |
| `signoz-telemetrystore-clickhouse-0-0` | 8123, 9000 | Cluster Network only | private | logs, traces, metrics storage |
| `signoz-telemetrykeeper-clickhousekeeper-0` | 9181, 9234 | Cluster Network only | private | ClickHouse coordination |
| `signoz-telemetrystore-migrator` | none | none | private/job | schema bootstrap and migrations |
| `signoz-telemetrystore-clickhouse-user-scripts` | none | none | private/job | official histogram function binary |

Never publish ClickHouse, PostgreSQL, the backend ingester, Query Service API, or OTLP ports merely to make the deployment work.

## Runflare deployment

Create or use one private Cluster Network and map these DNS/service aliases:

- existing collector -> `otel-gateway`; set secret environment `SIGNOZ_OTLP_HTTP_ENDPOINT=http://signoz-ingester:4318`.
- backend ingester -> `signoz-ingester:4318` reachable from the collector.
- `signoz-signoz-0` -> `signoz-signoz-0:8080` for the public frontend route.
- all backend services use the names in `deploy/compose.yaml` on `signoz-network`.

Set `POSTGRES_PASSWORD` as a Runflare secret. Do not commit its value. The SigNoz DSN is built from that secret at startup. Set `LOW_CARDINAL_EXCEPTION_GROUPING` only if required by the official collector image; leave it secret-free.

Startup order is: ClickHouse Keeper -> ClickHouse user scripts -> ClickHouse -> migrator (`ready`, `bootstrap`, `sync up`, `async up`) -> Query Service and backend ingester. The existing collector may start independently and retries its exporter until the private ingester is ready.

ClickHouse data is mounted from the existing Runflare volume path `/signoz-clickhouse` to `/var/lib/clickhouse`. Do not delete or recreate that volume. Five GB is initial/development capacity and must be expanded before sustained telemetry ingestion.

### Domain routing

The current `https://signoz.pumograph.ir/healthz` route must remain pointed at the existing collector until a supported Runflare route is configured. The final UI route should point `https://signoz.pumograph.ir` to `signoz-signoz-0:8080`. Because a single hostname cannot generally target both services, Runflare must either provide path-based routing with `/healthz` explicitly sent to `otel-gateway:8000`, or retain a separate collector health hostname and update the health-check target. Do not switch the domain blindly: verify the collector health route returns `200` after the change.

## Resource attributes

Applications should send `service.name`, `service.version`, `deployment.environment`, `host.name`, `container.name`, `request_id`, and native trace/span IDs. Agents may additionally send `agent.name`, `agent.model`, `task.id`, and `workflow.id`. The gateway redacts common credential-shaped attributes; it does not invent missing telemetry.

## Verification

Run syntax and Compose validation locally:

```bash
python -m py_compile scripts/verify_signoz.py
POSTGRES_PASSWORD='[REDACTED]' docker compose -f deploy/compose.yaml config
```

Check collector liveness and Query Service readiness separately:

```bash
python scripts/verify_signoz.py \
  --collector https://collector-health.example/ \
  --query https://signoz.pumograph.ir/
```

Expected: `collector_liveness.status == 200` and `query_readiness.status == 200`. A collector `200` alone is not Query Service readiness.

After Runflare deployment, send one deterministic readiness log (the script adds `service.name=signoz-readiness-test`, `service.version=readiness`, `deployment.environment=verification`, `request_id`, and `task.id`):

```bash
python scripts/verify_signoz.py \
  --collector https://collector-health.example/ \
  --query https://signoz.pumograph.ir/ \
  --send-readiness-log
```

Then use the real SigNoz UI or Query Service `/api/v5/query_range` with a valid query payload to search `service.name = signoz-readiness-test` and confirm the request/trace identifiers. Repeat with one OTLP trace and one OTLP metric, and record the returned identifiers. The verifier accepts `--query-payload FILE --query-path /api/v5/query_range` for that actual search; it never treats `/healthz` as search evidence.

## Verification status

`IMPLEMENTED`: official pinned backend topology, non-destructive ClickHouse mount, secret interpolation, preserved collector configuration, and separate readiness/e2e verification tooling.

`VALIDATED`: local Python syntax and static configuration checks only, until Runflare is exercised.

`REQUIRES RUNFLARE ACTION`: deploy backend services, create Cluster Network mappings, set secrets, route the frontend domain while preserving collector health, and run searchable logs/traces/metrics tests.

`BLOCKED`: no production-readiness claim is possible before end-to-end telemetry is actually found through the real SigNoz Query Service.
