# Runflare Docker deployment

This repository now has a root `Dockerfile`, because Runflare's Docker mode
requires one at the repository root.

The image runs the OpenTelemetry Collector gateway. It is deliberately not a
fake SigNoz UI and does not claim to contain ClickHouse or the SigNoz query
service. Deploy the official SigNoz bundle as the storage/query layer when the
Runflare service has sufficient resources and persistent storage.

Runflare settings:

- Repository: `pumoco/SigNoz-for-sajjad`
- Branch: `main`
- Build mode: Dockerfile
- Dockerfile path: `Dockerfile`
- Service port: `8000` (the Runflare-compatible public listener)
- Container bind: Collector listens on `0.0.0.0`
- Health endpoint: `/healthz` on port `8000`
- Public application port: `8000`
- OTLP `4317`/`4318` must remain private or be exposed only through Runflare
  internal networking; services must not send telemetry to the health port.

For this first Runflare smoke deployment, use the `8000` preset. OTLP/HTTP
still listens internally on `4318`; it is not exposed directly by this
single-port deployment. Put TLS/authentication/rate limiting at the platform
edge.

A collector-only deployment is not yet the complete SigNoz platform. The
complete production phase requires official SigNoz services, ClickHouse,
persistent volumes, protected UI access, and a verified telemetry query
round-trip.
