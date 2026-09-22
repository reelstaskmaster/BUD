FROM ghcr.io/tashfeenahmed/freellmapi:latest
USER root
COPY freellmapi-entrypoint.sh /usr/local/bin/freellmapi-railway-entrypoint.sh
RUN chmod +x /usr/local/bin/freellmapi-railway-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/freellmapi-railway-entrypoint.sh"]
