FROM busybox:1.37.0-uclibc AS probe
FROM otel/opentelemetry-collector-contrib:0.135.0
COPY --from=probe /bin/busybox /busybox
