# Observability connection plan

SigNoz is the central observability surface. This repository currently provides
an OTEL Collector deployment boundary; application SDK exporters are the next
integration layer.

## What will improve in the application repositories

Each service should emit the same safe event envelope:

- `timestamp`, `level`, `service`, `environment`
- `event_name`, `correlation_id`, `request_id`, `operation_id`
- `route` or `job`, `duration_ms`, `status`
- `dependency`, `deployment_version`, `error_class`
- safe domain fields such as `schema_version`, `execution_authorized`

The first wave should instrument request boundaries and dependency calls in
crypto-engine, MCP, analysis-cms, and the central DSS. It should not change
business decisions or add execution capability.

## Service improvements enabled by the node

- correlate one request across MCP, engine, market data, and DSS;
- measure endpoint and provider latency instead of guessing;
- detect stale or malformed market data before a NO_TRADE decision;
- measure background-job duration, failure, retry, and output age;
- distinguish application errors from provider, database, and deployment errors;
- detect missing telemetry and fail closed for health conclusions;
- compare deployments using error rate, latency, and data freshness;
- build read-only dashboards and bounded DSS/MCP diagnostic queries.

## Safe rollout order

1. Add SDKs and exporters with telemetry disabled by default.
2. Emit one synthetic test event from each service.
3. Verify the event in SigNoz by service and correlation ID.
4. Add request/dependency spans and structured log correlation.
5. Add metrics for latency, errors, freshness, queue age, and job outcomes.
6. Add bounded read-only dashboards and DSS/MCP query tools.
7. Run focused and full repository tests; verify no business-path regression.

No credentials, tokens, cookies, private payloads, or connection strings may be
sent to SigNoz. Observability must remain out-of-band and paper/read-only.
