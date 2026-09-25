FROM nousresearch/hermes-agent:latest
USER root
COPY --chmod=755 entrypoint.sh /usr/local/bin/hermes-railway-entrypoint.sh
ENV HERMES_HOME=/opt/data
EXPOSE 8642
CMD ["sh", "/usr/local/bin/hermes-railway-entrypoint.sh"]
