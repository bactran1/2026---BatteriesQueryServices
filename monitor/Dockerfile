FROM python:3.12-slim

ARG MONITOR_COMMIT=unknown

LABEL org.opencontainers.image.title="Battery Monitor" \
      org.opencontainers.image.revision="${MONITOR_COMMIT}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    BQM_HOST=0.0.0.0 \
    BQM_PORT=8080 \
    BQM_DATA_DIR=/data \
    BQM_BUILD_COMMIT=${MONITOR_COMMIT}

WORKDIR /app

COPY monitor/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY monitor/src ./src

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).read()"

CMD ["python", "-m", "battery_monitor"]
