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
- Service port: `4318` for external OTLP/HTTP, or the platform's required HTTP
  port if it requires one public listener
- Container bind: Collector listens on `0.0.0.0`
- Health endpoint: Collector health extension must be enabled before using
  `/` on port `13133`

For a first Runflare smoke deployment, expose OTLP/HTTP only and do not expose
4317 publicly. Put TLS/authentication/rate limiting at the platform edge.

A collector-only deployment is not yet the complete SigNoz platform. The
complete production phase requires official SigNoz services, ClickHouse,
persistent volumes, protected UI access, and a verified telemetry query
round-trip.
