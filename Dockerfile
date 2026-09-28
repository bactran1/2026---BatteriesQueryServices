FROM python:3.12-slim

ARG COLLECTOR_COMMIT=unknown
ARG COLLECTOR_BRANCH=unknown

LABEL org.opencontainers.image.title="Batteries Query Service" \
      org.opencontainers.image.revision="${COLLECTOR_COMMIT}" \
      org.opencontainers.image.ref.name="${COLLECTOR_BRANCH}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BQS_CONFIG=/config/config.toml \
    BQS_BUILD_COMMIT=${COLLECTOR_COMMIT} \
    BQS_BUILD_BRANCH=${COLLECTOR_BRANCH}

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).read()"

CMD ["python", "-m", "batteries_query_service"]
