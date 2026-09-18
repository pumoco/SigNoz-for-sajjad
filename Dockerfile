FROM otel/opentelemetry-collector-contrib:0.136.0

COPY otel/collector.config.yaml /etc/otelcol-contrib/config.yaml

EXPOSE 8000

CMD ["--config=/etc/otelcol-contrib/config.yaml"]
