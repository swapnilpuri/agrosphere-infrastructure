FROM busybox:1.37.0-uclibc AS probe
FROM jaegertracing/all-in-one:1.76.0
COPY --from=probe /bin/busybox /busybox
