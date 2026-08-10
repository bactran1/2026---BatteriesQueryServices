#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
case "${SCRIPT_PATH}" in
  */*) SCRIPT_DIR="$(cd -- "${SCRIPT_PATH%/*}" && pwd)" ;;
  *) SCRIPT_DIR="$(pwd)" ;;
esac
REPO_ROOT="${SCRIPT_DIR}"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.yml"
SERVICE_NAME="batteries-query-service"
DEFAULT_SERIAL_DEVICE="/dev/ttyUSB0"
DEFAULT_CONFIG_FILE="${REPO_ROOT}/config.toml"
FOLLOW_LOGS=0
HEALTH_CHECK=1
SKIP_GIT_UPDATE=0
USE_CACHE=0

usage() {
  printf '%s\n' \
"Update, build, and restart the Raspberry Pi battery collector." \
"" \
"Usage:" \
"  bash deploy-collector.sh [options]" \
"" \
"Options:" \
"  --serial-device PATH  Host USB serial device, including /dev/serial/by-id paths" \
"  --config PATH         Collector TOML file, default ./config.toml" \
"  --follow-logs         Follow container logs after deployment" \
"  --no-health-check     Skip the post-restart health check" \
"  --skip-git-update     Build the current local checkout without fetching Git" \
"  --use-cache           Allow Docker to reuse cached build layers" \
"  -h, --help            Show this help" \
"" \
"Environment:" \
"  COLLECTOR_SERIAL_DEVICE  Same as --serial-device" \
"  COLLECTOR_CONFIG_FILE    Same as --config" \
"  COLLECTOR_IMAGE_NAME     Image name, default batteries-query-service" \
"  COLLECTOR_IMAGE_TAG      Image tag; default is the current Git commit SHA" \
"" \
"Examples:" \
"  bash deploy-collector.sh" \
"  bash deploy-collector.sh --serial-device /dev/serial/by-id/usb-Your_Adapter" \
"  bash deploy-collector.sh --skip-git-update --use-cache"
}

log() {
  printf '[battery-collector] %s\n' "$*"
}

fail() {
  printf '[battery-collector] ERROR: %s\n' "$*" >&2
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

  export COLLECTOR_COMMIT="${COLLECTOR_COMMIT:-${commit}}"
  export COLLECTOR_IMAGE_NAME="${COLLECTOR_IMAGE_NAME:-batteries-query-service}"
  export COLLECTOR_IMAGE_TAG="${COLLECTOR_IMAGE_TAG:-${tag}}"
}

resolve_config_file() {
  local requested="${COLLECTOR_CONFIG_FILE:-${DEFAULT_CONFIG_FILE}}"

  case "${requested}" in
    /*) export COLLECTOR_CONFIG_FILE="${requested}" ;;
    *) export COLLECTOR_CONFIG_FILE="${REPO_ROOT}/${requested#./}" ;;
  esac

  if [[ ! -f "${COLLECTOR_CONFIG_FILE}" ]]; then
    if [[ "${COLLECTOR_CONFIG_FILE}" == "${DEFAULT_CONFIG_FILE}" && -f "${REPO_ROOT}/config.example.toml" ]]; then
      cp "${REPO_ROOT}/config.example.toml" "${COLLECTOR_CONFIG_FILE}"
      log "Created ${COLLECTOR_CONFIG_FILE} from config.example.toml."
    else
      fail "Collector config does not exist: ${COLLECTOR_CONFIG_FILE}"
    fi
  fi
}

container_exists() {
  docker container inspect "${SERVICE_NAME}" >/dev/null 2>&1
}

explain_container_start_failure() {
  local output="$1"

  if [[ "${output}" == *"error gathering device information"* || "${output}" == *"no such file or directory"* ]]; then
    printf '%s\n' "${output}" >&2
    fail "Docker could not attach ${COLLECTOR_SERIAL_DEVICE}. Confirm the USB adapter is connected and use --serial-device with its current path."
  fi

  if [[ "${output}" == *"net.ipv4.ip_unprivileged_port_start"* ]]; then
    printf '%s\n' "${output}" >&2
    fail "Docker cannot start containers because the host runtime is blocked from setting net.ipv4.ip_unprivileged_port_start. This is a Docker host issue, not a collector image issue."
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
    --serial-device)
      [[ $# -ge 2 ]] || fail "--serial-device requires a path"
      export COLLECTOR_SERIAL_DEVICE="$2"
      shift 2
      ;;
    --config)
      [[ $# -ge 2 ]] || fail "--config requires a path"
      export COLLECTOR_CONFIG_FILE="$2"
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

export COLLECTOR_SERIAL_DEVICE="${COLLECTOR_SERIAL_DEVICE:-${DEFAULT_SERIAL_DEVICE}}"
mkdir -p "${REPO_ROOT}/data/collector"

cd "${REPO_ROOT}"
update_git_checkout
resolve_config_file
set_image_identity

if [[ ! -e "${COLLECTOR_SERIAL_DEVICE}" ]]; then
  log "WARNING: Serial device is not currently present: ${COLLECTOR_SERIAL_DEVICE}"
fi

log "Serial device: ${COLLECTOR_SERIAL_DEVICE} -> /dev/ttyUSB0"
log "Config file: ${COLLECTOR_CONFIG_FILE}"
log "Image: ${COLLECTOR_IMAGE_NAME}:${COLLECTOR_IMAGE_TAG}"
log "Build commit: ${COLLECTOR_COMMIT}"
log "Building ${SERVICE_NAME} from the latest available Git commit..."
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

log "Deployment complete. Collector API: http://localhost:8000"

if [[ "${FOLLOW_LOGS}" -eq 1 ]]; then
  "${COMPOSE[@]}" -f "${COMPOSE_FILE}" logs -f "${SERVICE_NAME}"
fi
