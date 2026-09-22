FROM ghcr.io/tashfeenahmed/freellmapi:latest
USER root
COPY --chmod=755 entrypoint.sh /usr/local/bin/freellmapi-railway-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/freellmapi-railway-entrypoint.sh"]
