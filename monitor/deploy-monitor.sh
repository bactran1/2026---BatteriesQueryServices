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
SKIP_GIT_UPDATE=0
USE_CACHE=0

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
"  --skip-git-update     Build the current local checkout without fetching Git" \
"  --use-cache           Allow Docker to reuse cached build layers" \
"  -h, --help            Show this help" \
"" \
"Environment:" \
"  BQM_COLLECTOR_URL     Same as --collector-url" \
"  BQM_RACK_NAME         Rack name shown on the dashboard" \
"  BQM_RACK_LOCATION     Rack location shown on the dashboard" \
"  BQM_BATTERY_NAMES     Comma-separated battery names" \
"  BQM_BATTERY_IPS       Comma-separated battery IP addresses" \
"  BQM_BATTERY_MODELS    Comma-separated battery models" \
"  MONITOR_IMAGE_NAME    Image name, default battery-monitor" \
"  MONITOR_IMAGE_TAG     Image tag; default is the current Git commit SHA" \
"" \
"Examples:" \
"  bash monitor/deploy-monitor.sh" \
"  bash monitor/deploy-monitor.sh --collector-url http://192.168.1.50:8000" \
"  BQM_COLLECTOR_URL=http://raspberrypi.local:8000 bash monitor/deploy-monitor.sh" \
"  bash monitor/deploy-monitor.sh --skip-git-update --use-cache"
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

git_is_available() {
  command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1
}

git_worktree_is_clean() {
  git diff --quiet --ignore-submodules -- &&
    git diff --cached --quiet --ignore-submodules --
}

update_git_checkout() {
  local branch
  local upstream
  local remote_ref
  local before
  local after

  if [[ "${SKIP_GIT_UPDATE}" -eq 1 ]]; then
    log "Skipping Git update; building the current local checkout."
    return 0
  fi

  if ! git_is_available; then
    log "No Git checkout found; building the files currently on disk."
    return 0
  fi

  if ! git_worktree_is_clean; then
    fail "The Git working tree has local changes. Commit, stash, or rerun with --skip-git-update to build the current checkout."
  fi

  branch="$(git branch --show-current)"
  if [[ -z "${branch}" ]]; then
    log "Repository is in detached HEAD; building current commit."
    return 0
  fi

  upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
  if [[ -n "${upstream}" ]]; then
    remote_ref="${upstream}"
    log "Fetching latest ${remote_ref}..."
    git fetch --prune "${remote_ref%%/*}"
  elif git rev-parse --verify --quiet "origin/${branch}" >/dev/null; then
    remote_ref="origin/${branch}"
    log "Fetching latest ${remote_ref}..."
    git fetch --prune origin
  else
    log "No upstream branch found for ${branch}; building current commit."
    return 0
  fi

  before="$(git rev-parse --short=12 HEAD)"
  git merge --ff-only "${remote_ref}"
  after="$(git rev-parse --short=12 HEAD)"

  if [[ "${before}" == "${after}" ]]; then
    log "Git checkout is already at latest commit ${after}."
  else
    log "Updated Git checkout from ${before} to ${after}."
  fi
}

set_image_identity() {
  local commit
  local tag

  if git_is_available; then
    commit="$(git rev-parse HEAD)"
    tag="$(git rev-parse --short=12 HEAD)"
  else
    commit="unknown"
    tag="$(date -u +%Y%m%d%H%M%S)"
  fi

  export MONITOR_COMMIT="${MONITOR_COMMIT:-${commit}}"
  export MONITOR_IMAGE_NAME="${MONITOR_IMAGE_NAME:-battery-monitor}"
  export MONITOR_IMAGE_TAG="${MONITOR_IMAGE_TAG:-${tag}}"
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
    --skip-git-update)
      SKIP_GIT_UPDATE=1
      shift
      ;;
    --use-cache)
      USE_CACHE=1
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
update_git_checkout
set_image_identity

log "Collector URL: ${BQM_COLLECTOR_URL}"
log "Image: ${MONITOR_IMAGE_NAME}:${MONITOR_IMAGE_TAG}"
log "Build commit: ${MONITOR_COMMIT}"
log "Building ${SERVICE_NAME} from the current Git commit..."
BUILD_ARGS=(build --pull)
if [[ "${USE_CACHE}" -eq 0 ]]; then
  BUILD_ARGS+=(--no-cache)
fi
"${COMPOSE[@]}" -f "${COMPOSE_FILE}" "${BUILD_ARGS[@]}" "${SERVICE_NAME}"

if container_exists; then
  log "Existing ${SERVICE_NAME} container found; updating it with the new image..."
else
  log "No existing ${SERVICE_NAME} container found; creating it..."
fi

compose_up

RUNNING_IMAGE="$(docker inspect --format '{{.Config.Image}}' "${SERVICE_NAME}" 2>/dev/null || true)"
if [[ -n "${RUNNING_IMAGE}" ]]; then
  log "Running image: ${RUNNING_IMAGE}"
fi

if [[ "${HEALTH_CHECK}" -eq 1 ]]; then
  wait_for_health
fi

log "Deployment complete. Dashboard: http://localhost:8080"

if [[ "${FOLLOW_LOGS}" -eq 1 ]]; then
  "${COMPOSE[@]}" -f "${COMPOSE_FILE}" logs -f "${SERVICE_NAME}"
fi
