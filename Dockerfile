FROM otel/opentelemetry-collector-contrib:0.136.0

COPY otel/collector.config.yaml /etc/otelcol-contrib/config.yaml

EXPOSE 4317 4318 13133

CMD ["--config=/etc/otelcol-contrib/config.yaml"]
