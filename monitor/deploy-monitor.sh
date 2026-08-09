#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
case "${SCRIPT_PATH}" in
  */*) SCRIPT_DIR="$(cd -- "${SCRIPT_PATH%/*}" && pwd)" ;;
  *) SCRIPT_DIR="$(pwd)" ;;
esac
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.monitor.yml"
SERVICE_NAME="battery-monitor"
DEFAULT_COLLECTOR_URL="http://raspberrypi.local:8000"
FOLLOW_LOGS=0
HEALTH_CHECK=1

usage() {
  printf '%s\n' \
"Build and restart the Battery Monitor container." \
"" \
"Usage:" \
"  bash monitor/deploy-monitor.sh [options]" \
"" \
"Options:" \
"  --collector-url URL   Collector URL, for example http://192.168.1.50:8000" \
"  --follow-logs         Follow container logs after deployment" \
"  --no-health-check     Skip the post-restart health check" \
"  -h, --help            Show this help" \
"" \
"Environment:" \
"  BQM_COLLECTOR_URL     Same as --collector-url" \
"" \
"Examples:" \
"  bash monitor/deploy-monitor.sh" \
"  bash monitor/deploy-monitor.sh --collector-url http://192.168.1.50:8000" \
"  BQM_COLLECTOR_URL=http://raspberrypi.local:8000 bash monitor/deploy-monitor.sh"
}

log() {
  printf '[battery-monitor] %s\n' "$*"
}

fail() {
  printf '[battery-monitor] ERROR: %s\n' "$*" >&2
  exit 1
}

compose_command() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
  else
    fail "Docker Compose is not installed. Install the Docker Compose plugin or docker-compose."
  fi
}

container_exists() {
  docker container inspect "${SERVICE_NAME}" >/dev/null 2>&1
}

explain_container_start_failure() {
  local output="$1"

  if [[ "${output}" == *"net.ipv4.ip_unprivileged_port_start"* ]]; then
    printf '%s\n' "${output}" >&2
    fail "Docker cannot start containers on this host because runc/containerd is blocked from setting net.ipv4.ip_unprivileged_port_start. This is a host-level Docker/LXC/AppArmor/user-namespace issue, not a Battery Monitor image issue. Test with: docker run --rm hello-world. If hello-world fails the same way, update/fix the x86 Docker host, move Docker out of an unprivileged LXC/container, or run it in a VM/bare-metal Docker host."
  fi

  printf '%s\n' "${output}" >&2
  fail "Docker Compose failed to start ${SERVICE_NAME}."
}

compose_up() {
  local output

  if ! output="$("${COMPOSE[@]}" -f "${COMPOSE_FILE}" up -d --force-recreate --remove-orphans "${SERVICE_NAME}" 2>&1)"; then
    explain_container_start_failure "${output}"
  fi

  printf '%s\n' "${output}"
}

wait_for_health() {
  local attempt
  local state

  log "Waiting for ${SERVICE_NAME} to become healthy..."
  for attempt in $(seq 1 60); do
    state="$(
      docker inspect \
        --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "${SERVICE_NAME}" 2>/dev/null || true
    )"

    if [[ "${state}" == "healthy" || "${state}" == "running" ]]; then
      log "${SERVICE_NAME} is ${state}."
      return 0
    fi

    sleep 2
  done

  docker logs --tail 80 "${SERVICE_NAME}" >&2 || true
  fail "${SERVICE_NAME} did not become healthy in time."
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --collector-url)
      [[ $# -ge 2 ]] || fail "--collector-url requires a URL"
      export BQM_COLLECTOR_URL="$2"
      shift 2
      ;;
    --follow-logs)
      FOLLOW_LOGS=1
      shift
      ;;
    --no-health-check)
      HEALTH_CHECK=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
done

[[ -f "${COMPOSE_FILE}" ]] || fail "Missing ${COMPOSE_FILE}"
command -v docker >/dev/null 2>&1 || fail "Docker is not installed or not on PATH."
docker info >/dev/null 2>&1 || fail "Docker daemon is not reachable. Check Docker and user permissions."
compose_command

export BQM_COLLECTOR_URL="${BQM_COLLECTOR_URL:-${DEFAULT_COLLECTOR_URL}}"
mkdir -p "${REPO_ROOT}/data/monitor"

cd "${REPO_ROOT}"

log "Collector URL: ${BQM_COLLECTOR_URL}"
log "Building the latest ${SERVICE_NAME} image..."
"${COMPOSE[@]}" -f "${COMPOSE_FILE}" build --pull "${SERVICE_NAME}"

if container_exists; then
  log "Existing ${SERVICE_NAME} container found; updating it with the new image..."
else
  log "No existing ${SERVICE_NAME} container found; creating it..."
fi

compose_up

if [[ "${HEALTH_CHECK}" -eq 1 ]]; then
  wait_for_health
fi

log "Deployment complete. Dashboard: http://localhost:8080"

if [[ "${FOLLOW_LOGS}" -eq 1 ]]; then
  "${COMPOSE[@]}" -f "${COMPOSE_FILE}" logs -f "${SERVICE_NAME}"
fi
