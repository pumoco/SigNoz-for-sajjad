FROM otel/opentelemetry-collector-contrib:0.136.0

COPY otel/collector.config.yaml /etc/otelcol-contrib/config.yaml

ENV PORT=8000 \
    SIGNOZ_OTLP_HTTP_ENDPOINT=http://signoz-ingester:4318

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
  CMD ["wget", "--spider", "-q", "http://127.0.0.1:8000/healthz"]

CMD ["--config=/etc/otelcol-contrib/config.yaml"]
