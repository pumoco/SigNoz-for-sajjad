# SigNoz v0.142.1 deployment

This repository contains an executable Compose definition synced from the official SigNoz Foundry deployment example at GitHub commit `997cff5c40333f4b7f3b7f8d710a2f7e65c8f4af`. The SigNoz and collector images remain pinned to `v0.142.1`; no Redis or placeholder nginx service is used.

Deployment definition

- Primary file: `deploy/compose.yaml`
- Root Compose entry point: `docker-compose.yml` includes the deployment file.
- All images are explicitly tagged: SigNoz and SigNoz OTEL collector `v0.142.1`, gateway collector `0.136.0`, and ClickHouse/Keeper `25.12.5`.
- `deploy/ingester`, `deploy/telemetrykeeper`, and `deploy/telemetrystore` are copied from that Foundry deployment example; only the gateway, image pins, secret interpolation, private port exposure, and existing ClickHouse mount are repository adaptations.
- `signoz-clickhouse` is an existing external Runflare volume mounted at `/var/lib/clickhouse`. It must not be deleted, recreated, or migrated destructively.
- SigNoz uses its official embedded SQLite metastore mode; the database is stored at `/signoz-clickhouse/metastore/signoz.db` on the existing disk. No PostgreSQL service, DSN, migration, or health check is present.

Services and network

All services are on the private `signoz-network`, which must map to the Runflare Cluster Network:

- `otel-gateway`: OpenTelemetry Collector, internal 4317/4318 and health 8000.
- `ingester`: SigNoz OpenTelemetry ingestion backend, internal 4317/4318 and health 13133.
- `signoz-signoz-0`: SigNoz Query Service and frontend, internal HTTP 8080; embedded SQLite metastore at `/var/lib/signoz/signoz.db` (single-node metadata storage).
- `signoz-telemetrystore-clickhouse-0-0`: ClickHouse, internal native 9000 and HTTP 8123 only.
- `signoz-telemetrykeeper-clickhousekeeper-0`: ClickHouse Keeper, internal client 9181 only.
- `signoz-telemetrystore-migrator`: required ClickHouse schema migration job.
- `signoz-telemetrystore-clickhouse-user-scripts`: required histogram executable initialization job.

Runflare routing

Route `signoz.pumograph.ir` to `signoz-signoz-0:8080`. Do not route it to the collector or nginx. Keep the collector health check available as a separate private/public health mapping, for example `collector-health.pumograph.ir` to `otel-gateway:8000`, because one hostname cannot safely route both the frontend root and `/healthz` without a supported Runflare path router.

Set `SIGNOZ_OTLP_HTTP_ENDPOINT=http://signoz-ingester:4318` for `otel-gateway`. The collector exports to the actual ingestion service alias `signoz-ingester`, not a nonexistent `signoz` service. Keep OTLP ports private; only the frontend route and an explicitly approved collector health mapping may be public.

Required variables and secrets

- `SIGNOZ_OTLP_HTTP_ENDPOINT` — required for the collector; recommended value `http://signoz-ingester:4318`.
- No PostgreSQL variable or secret is required. SigNoz uses `SIGNOZ_SQLSTORE_PROVIDER=sqlite` and `SIGNOZ_SQLSTORE_SQLITE_PATH=/var/lib/signoz/signoz.db`.
- `COLLECTOR_HEALTH_PORT` — optional private/approved health mapping for host port 8000; it does not change the collector listener.

Startup order

1. ClickHouse Keeper becomes healthy.
2. ClickHouse user scripts finish successfully.
3. ClickHouse becomes healthy using the existing persistent data volume.
4. The migrator runs `ready`, `bootstrap`, synchronous, and asynchronous migrations.
5. `signoz-signoz-0` starts with its embedded SQLite metastore and ClickHouse; its health endpoint is `/api/v1/health` on port 8080.
6. `ingester` starts after ClickHouse and migrations and exposes OTLP internally.
7. `otel-gateway` accepts telemetry on its unchanged 4317/4318 listeners and exports OTLP/HTTP to `signoz-ingester:4318`.

Verification

```sh
python -m py_compile scripts/verify_signoz.py
python scripts/verify_signoz.py \
  --collector http://otel-gateway:8000 \
  --query http://signoz-signoz-0:8080 \
  --backend http://ingester:13133 \
  --clickhouse http://signoz-telemetrystore-clickhouse-0-0:8123 \
  --send-otlp \
  --logs-payload payloads/logs.json \
  --traces-payload payloads/traces.json \
  --metrics-payload payloads/metrics.json
```

The verifier reports independently: collector liveness, Query/API readiness, backend readiness, ClickHouse readiness, OTLP ingestion, searchable logs, searchable traces, and searchable metrics. Search payloads must be real Query Service payloads; the script does not fake SigNoz APIs.

Required local checks:

```sh
python - <<'PY'
from pathlib import Path
import yaml
for path in [Path('deploy/compose.yaml'), Path('docker-compose.yml'), *Path('deploy').rglob('*.yaml')]:
    yaml.safe_load(path.read_text())
    print(path)
PY
python -m py_compile scripts/verify_signoz.py
git diff --check
```

No deployment, DNS change, Runflare mutation, or push is performed by repository validation.
