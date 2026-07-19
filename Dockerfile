FROM python:3.12-slim

RUN useradd --create-home --uid 10001 ups-monitor
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

ENV PYTHONPATH=/app/src \
    UPS_MONITOR_BIND=0.0.0.0 \
    UPS_MONITOR_PORT=8787 \
    UPS_MONITOR_DATABASE=/data/ups-monitor.sqlite3

RUN mkdir -p /data /config && chown -R ups-monitor:ups-monitor /data /config
USER ups-monitor
EXPOSE 8787
VOLUME ["/data", "/config"]
CMD ["python3", "-m", "ups_monitor"]
