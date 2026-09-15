#!/usr/bin/env bash
set -Eeuo pipefail

# Run from a private snapshot so a fast-forward can safely update this file while
# the current check is still executing. The next timer run uses the new version.
if [[ "${BATTERY_AUTO_DEPLOY_SNAPSHOT:-0}" != "1" ]]; then
  snapshot="$(mktemp "${TMPDIR:-/tmp}/battery-auto-deploy.XXXXXX")"
  cp -- "${BASH_SOURCE[0]}" "${snapshot}"
  chmod 700 "${snapshot}"
  export BATTERY_AUTO_DEPLOY_SNAPSHOT=1
  export BATTERY_AUTO_DEPLOY_SNAPSHOT_PATH="${snapshot}"
  export BATTERY_AUTO_DEPLOY_ORIGINAL_SCRIPT="${BASH_SOURCE[0]}"
  exec /usr/bin/env bash "${snapshot}" "$@"
fi

cleanup() {
  rm -f -- "${BATTERY_AUTO_DEPLOY_SNAPSHOT_PATH:-}"
}
trap cleanup EXIT

ORIGINAL_SCRIPT="${BATTERY_AUTO_DEPLOY_ORIGINAL_SCRIPT:-${BASH_SOURCE[0]}}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${ORIGINAL_SCRIPT}")" && pwd)"
SERVICE=""
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REMOTE="origin"
BRANCH="master"
ARGUMENTS_FILE=""
STATE_DIR="${AUTO_DEPLOY_STATE_DIR:-${XDG_STATE_HOME:-${HOME}/.local/state}/battery-auto-deploy}"
FORCE=0
DRY_RUN=0

usage() {
  printf '%s\n' \
"Watch a Git branch once and deploy the affected battery service." \
"" \
"Usage:" \
"  bash deploy/auto-deploy.sh --service monitor|collector [options]" \
"" \
"Options:" \
"  --service NAME         monitor or collector" \
"  --repo PATH            Repository checkout, default is this script's repository" \
"  --remote NAME          Git remote, default origin" \
"  --branch NAME          Watched branch, default master" \
"  --arguments-file PATH  Extra deploy-script arguments, one literal argument per line" \
"  --state-dir PATH       Successful-check state directory" \
"  --force                Deploy even when no relevant commit is pending" \
"  --dry-run              Fetch and report without changing the checkout or container" \
"  -h, --help             Show this help"
}

log() {
  printf '[battery-auto-deploy:%s] %s\n' "${SERVICE:-setup}" "$*"
}

fail() {
  printf '[battery-auto-deploy:%s] ERROR: %s\n' "${SERVICE:-setup}" "$*" >&2
  exit 1
}

write_commit() {
  local path="$1"
  local commit="$2"
  local temporary="${path}.tmp.$$"

  printf '%s\n' "${commit}" > "${temporary}"
  mv -f -- "${temporary}" "${path}"
}

read_commit() {
  local path="$1"
  local commit=""

  [[ -f "${path}" ]] || return 0
  IFS= read -r commit < "${path}" || true
  if [[ "${commit}" =~ ^[0-9a-fA-F]{40}$ ]] &&
     git -C "${REPO_ROOT}" cat-file -e "${commit}^{commit}" 2>/dev/null; then
    printf '%s\n' "${commit,,}"
  fi
}

container_revision() {
  docker inspect \
    --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
    "${CONTAINER_NAME}" 2>/dev/null || true
}

container_is_healthy() {
  local status
  local health

  status="$(docker inspect --format '{{.State.Status}}' "${CONTAINER_NAME}" 2>/dev/null || true)"
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "${CONTAINER_NAME}" 2>/dev/null || true)"
  [[ "${status}" == "running" && ( -z "${health}" || "${health}" == "healthy" ) ]]
}

is_relevant_path() {
  local path="$1"

  case "${SERVICE}" in
    monitor)
      case "${path}" in
        monitor/*|docker-compose.monitor.yml) return 0 ;;
      esac
      ;;
    collector)
      case "${path}" in
        src/*|Dockerfile|docker-compose.yml|requirements.txt|pyproject.toml|config.toml|config.example.toml|deploy-collector.sh) return 0 ;;
      esac
      ;;
  esac
  return 1
}

load_deploy_arguments() {
  local argument
  DEPLOY_ARGUMENTS=()

  [[ -n "${ARGUMENTS_FILE}" && -f "${ARGUMENTS_FILE}" ]] || return 0
  while IFS= read -r argument || [[ -n "${argument}" ]]; do
    [[ -z "${argument}" || "${argument}" == \#* ]] && continue
    [[ "${argument}" != "--follow-logs" ]] || fail "--follow-logs cannot be used by an unattended systemd service."
    [[ "${argument}" != "--skip-git-update" ]] || continue
    DEPLOY_ARGUMENTS+=("${argument}")
  done < "${ARGUMENTS_FILE}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)
      [[ $# -ge 2 ]] || fail "--service requires monitor or collector"
      SERVICE="$2"
      shift 2
      ;;
    --repo)
      [[ $# -ge 2 ]] || fail "--repo requires a path"
      REPO_ROOT="$2"
      shift 2
      ;;
    --remote)
      [[ $# -ge 2 ]] || fail "--remote requires a name"
      REMOTE="$2"
      shift 2
      ;;
    --branch)
      [[ $# -ge 2 ]] || fail "--branch requires a name"
      BRANCH="$2"
      shift 2
      ;;
    --arguments-file)
      [[ $# -ge 2 ]] || fail "--arguments-file requires a path"
      ARGUMENTS_FILE="$2"
      shift 2
      ;;
    --state-dir)
      [[ $# -ge 2 ]] || fail "--state-dir requires a path"
      STATE_DIR="$2"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
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

[[ -d "${REPO_ROOT}" ]] || fail "Repository directory does not exist: ${REPO_ROOT}"
REPO_ROOT="$(cd -- "${REPO_ROOT}" && pwd)"

case "${SERVICE}" in
  monitor)
    CONTAINER_NAME="battery-monitor"
    DEPLOY_SCRIPT="${REPO_ROOT}/monitor/deploy-monitor.sh"
    ;;
  collector)
    CONTAINER_NAME="batteries-query-service"
    DEPLOY_SCRIPT="${REPO_ROOT}/deploy-collector.sh"
    ;;
  *)
    fail "--service must be monitor or collector"
    ;;
esac

command -v git >/dev/null 2>&1 || fail "Git is not installed."
command -v docker >/dev/null 2>&1 || fail "Docker is not installed."
command -v flock >/dev/null 2>&1 || fail "flock is not installed; install the util-linux package."
[[ -d "${REPO_ROOT}/.git" ]] || fail "Not a Git checkout: ${REPO_ROOT}"
[[ -f "${DEPLOY_SCRIPT}" ]] || fail "Deployment script is missing: ${DEPLOY_SCRIPT}"
docker info >/dev/null 2>&1 || fail "Docker daemon is not reachable by user $(id -un)."

mkdir -p "${STATE_DIR}"
exec 9>"${STATE_DIR}/${SERVICE}.lock"
if ! flock -n 9; then
  log "Another update check is already running; leaving it in control."
  exit 0
fi

current_branch="$(git -C "${REPO_ROOT}" branch --show-current)"
[[ "${current_branch}" == "${BRANCH}" ]] ||
  fail "Checkout is on '${current_branch:-detached HEAD}', not '${BRANCH}'. Switch this deployment checkout to ${BRANCH}."

dirty_status="$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=normal)"
local_config_modified=0
if [[ -n "${dirty_status}" ]]; then
  unexpected_dirty=""
  while IFS= read -r status_line; do
    if [[ "${status_line}" == " M config.toml" ]]; then
      local_config_modified=1
    elif [[ -n "${status_line}" ]]; then
      unexpected_dirty+="${status_line}"$'\n'
    fi
  done <<< "${dirty_status}"
  if [[ -n "${unexpected_dirty}" ]]; then
    printf '%s' "${unexpected_dirty}" >&2
    fail "Git checkout has local changes outside the permitted host config.toml file. Commit, stash, or remove them before automatic deployment."
  fi
  log "Keeping the host's local config.toml settings during this update."
fi

git -C "${REPO_ROOT}" remote get-url "${REMOTE}" >/dev/null 2>&1 ||
  fail "Git remote '${REMOTE}' is not configured."
git check-ref-format --branch "${BRANCH}" >/dev/null 2>&1 ||
  fail "Invalid branch name: ${BRANCH}"

log "Checking ${REMOTE}/${BRANCH}..."
GIT_TERMINAL_PROMPT=0 git -C "${REPO_ROOT}" fetch --quiet --prune "${REMOTE}" \
  "+refs/heads/${BRANCH}:refs/remotes/${REMOTE}/${BRANCH}"
target="$(git -C "${REPO_ROOT}" rev-parse "refs/remotes/${REMOTE}/${BRANCH}")"
head="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
seen_file="${STATE_DIR}/${SERVICE}.seen"
deployed_file="${STATE_DIR}/${SERVICE}.deployed"
seen="$(read_commit "${seen_file}")"
deployed="$(read_commit "${deployed_file}")"
running_revision="$(container_revision)"
running_revision="${running_revision,,}"

if [[ -z "${deployed}" && "${running_revision}" =~ ^[0-9a-f]{40}$ ]] &&
   git -C "${REPO_ROOT}" cat-file -e "${running_revision}^{commit}" 2>/dev/null; then
  deployed="${running_revision}"
fi
if [[ -z "${seen}" ]]; then
  seen="${deployed}"
fi

deploy_required="${FORCE}"
reason="no relevant files changed"
if [[ "${FORCE}" -eq 1 ]]; then
  reason="manual force"
fi
if ! container_is_healthy; then
  deploy_required=1
  reason="container is missing, stopped, or unhealthy"
elif [[ -n "${deployed}" && "${running_revision}" != "${deployed}" ]]; then
  deploy_required=1
  reason="running image does not match the last successful deployment"
fi

changed_paths=""
if [[ "${target}" != "${seen}" ]]; then
  if [[ -n "${seen}" ]] && git -C "${REPO_ROOT}" merge-base --is-ancestor "${seen}" "${target}"; then
    changed_paths="$(git -C "${REPO_ROOT}" diff --name-only "${seen}" "${target}")"
    while IFS= read -r path; do
      if [[ -n "${path}" ]] && is_relevant_path "${path}"; then
        deploy_required=1
        reason="relevant files changed"
        break
      fi
    done <<< "${changed_paths}"
  else
    deploy_required=1
    reason="no trustworthy prior master commit is available"
  fi
fi

if [[ "${target}" == "${seen}" && "${deploy_required}" -eq 0 ]]; then
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "Dry run: no new commit and no deployment is required."
    exit 0
  fi
  write_commit "${seen_file}" "${target}"
  if [[ -n "${deployed}" ]]; then
    write_commit "${deployed_file}" "${deployed}"
  fi
  log "No new commit; ${CONTAINER_NAME} already matches the last successful deployment."
  exit 0
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
  log "Dry run: target ${target:0:12}; deployment required=${deploy_required} (${reason})."
  if [[ -n "${changed_paths}" ]]; then
    printf '%s\n' "${changed_paths}"
  fi
  exit 0
fi

if [[ "${head}" != "${target}" ]]; then
  git -C "${REPO_ROOT}" merge-base --is-ancestor "${head}" "${target}" ||
    fail "Local ${BRANCH} cannot fast-forward to ${REMOTE}/${BRANCH}; reconcile the checkout manually."
  if [[ "${local_config_modified}" -eq 1 ]] &&
     [[ -n "$(git -C "${REPO_ROOT}" diff --name-only "${head}" "${target}" -- config.toml)" ]]; then
    fail "${REMOTE}/${BRANCH} also changes config.toml. Preserve the host settings, restore a clean config.toml, and rerun after reconciling it manually."
  fi
  log "Fast-forwarding ${BRANCH} from ${head:0:12} to ${target:0:12}..."
  git -C "${REPO_ROOT}" merge --quiet --ff-only "${target}"
fi

if [[ "${deploy_required}" -eq 0 ]]; then
  write_commit "${seen_file}" "${target}"
  log "Updated the checkout to ${target:0:12}; this commit does not affect ${SERVICE}, so no image rebuild was needed."
  exit 0
fi

load_deploy_arguments
log "Deploying ${target:0:12}: ${reason}."
(cd "${REPO_ROOT}" && /usr/bin/env bash "${DEPLOY_SCRIPT}" "${DEPLOY_ARGUMENTS[@]}" --skip-git-update)

running_revision="$(container_revision)"
running_revision="${running_revision,,}"
[[ "${running_revision}" == "${target}" ]] ||
  fail "Deployment returned successfully, but ${CONTAINER_NAME} reports build ${running_revision:-unknown} instead of ${target}."
container_is_healthy || fail "${CONTAINER_NAME} is not healthy after deployment."

write_commit "${deployed_file}" "${target}"
write_commit "${seen_file}" "${target}"
log "Deployment ${target:0:12} is running and healthy."
