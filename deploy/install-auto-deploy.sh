#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
CONFIG_DIR="/etc/battery-auto-deploy"
LIBEXEC_DIR="/usr/local/libexec"
INTERVAL="5min"
RANDOM_DELAY="30s"
REMOTE="origin"
BRANCH="master"
RUN_NOW=1
UNINSTALL=0
RUN_USER=""
DEPLOY_ARGUMENTS=()

usage() {
  printf '%s\n' \
"Install automatic master-branch deployment for one battery service." \
"" \
"Usage:" \
"  sudo bash deploy/install-auto-deploy.sh monitor [options] [-- deploy arguments]" \
"  sudo bash deploy/install-auto-deploy.sh collector [options] [-- deploy arguments]" \
"" \
"Options:" \
"  --user USER       Linux user that owns the checkout and can run Docker" \
"  --interval TIME   Check interval understood by systemd, default 5min" \
"  --random-delay T  Timer jitter, default 30s" \
"  --remote NAME     Git remote, default origin" \
"  --branch NAME     Watched branch, default master" \
"  --no-run-now      Enable the timer without performing the first check now" \
"  --uninstall       Remove this service's timer and configuration" \
"  -h, --help        Show this help" \
"" \
"Everything after -- is saved as literal arguments for the existing deployment script." \
"Example:" \
"  sudo bash deploy/install-auto-deploy.sh monitor -- --collector-url http://192.168.10.194:8000" \
"  sudo bash deploy/install-auto-deploy.sh collector -- --inverter-host 192.168.20.138 --inverter-logger-serial 3503566593"
}

fail() {
  printf '[battery-auto-deploy:installer] ERROR: %s\n' "$*" >&2
  exit 1
}

[[ $# -ge 1 ]] || {
  usage
  exit 2
}

SERVICE="$1"
shift
case "${SERVICE}" in
  monitor)
    UNIT_BASE="battery-monitor-auto-deploy"
    DESCRIPTION="Battery Monitor automatic deployment"
    ;;
  collector)
    UNIT_BASE="battery-collector-auto-deploy"
    DESCRIPTION="Battery Collector automatic deployment"
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    fail "First argument must be monitor or collector."
    ;;
esac

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user)
      [[ $# -ge 2 ]] || fail "--user requires a Linux user"
      RUN_USER="$2"
      shift 2
      ;;
    --interval)
      [[ $# -ge 2 ]] || fail "--interval requires a duration"
      INTERVAL="$2"
      shift 2
      ;;
    --random-delay)
      [[ $# -ge 2 ]] || fail "--random-delay requires a duration"
      RANDOM_DELAY="$2"
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
    --no-run-now)
      RUN_NOW=0
      shift
      ;;
    --uninstall)
      UNINSTALL=1
      shift
      ;;
    --)
      shift
      DEPLOY_ARGUMENTS=("$@")
      break
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1 (put deployment-script options after --)"
      ;;
  esac
done

[[ "${EUID}" -eq 0 ]] || fail "Run this installer with sudo."
[[ "${INTERVAL}" =~ ^[0-9]+(s|min|h|d|week)$ ]] || fail "Unsupported --interval value: ${INTERVAL}"
[[ "${RANDOM_DELAY}" =~ ^[0-9]+(s|min|h|d)$ ]] || fail "Unsupported --random-delay value: ${RANDOM_DELAY}"
[[ "${REMOTE}" != *$'\n'* && -n "${REMOTE}" ]] || fail "Invalid remote name."
[[ "${BRANCH}" != *$'\n'* && -n "${BRANCH}" ]] || fail "Invalid branch name."

service_path="/etc/systemd/system/${UNIT_BASE}.service"
timer_path="/etc/systemd/system/${UNIT_BASE}.timer"

if [[ "${UNINSTALL}" -eq 1 ]]; then
  systemctl disable --now "${UNIT_BASE}.timer" >/dev/null 2>&1 || true
  systemctl stop "${UNIT_BASE}.service" >/dev/null 2>&1 || true
  rm -f -- "${service_path}" "${timer_path}"
  rm -f -- "${CONFIG_DIR}/${SERVICE}.repo" "${CONFIG_DIR}/${SERVICE}.branch" \
    "${CONFIG_DIR}/${SERVICE}.remote" "${CONFIG_DIR}/${SERVICE}.args" \
    "${CONFIG_DIR}/${SERVICE}.env"
  systemctl daemon-reload
  printf '[battery-auto-deploy:installer] Removed %s. Deployment state was preserved.\n' "${UNIT_BASE}"
  exit 0
fi

command -v systemctl >/dev/null 2>&1 || fail "systemd is required."
command -v git >/dev/null 2>&1 || fail "Git is not installed."
command -v docker >/dev/null 2>&1 || fail "Docker is not installed."
[[ -d "${REPO_ROOT}/.git" ]] || fail "Installer must run from a Git checkout."
git check-ref-format --branch "${BRANCH}" >/dev/null 2>&1 || fail "Invalid branch name: ${BRANCH}"
git -C "${REPO_ROOT}" remote get-url "${REMOTE}" >/dev/null 2>&1 ||
  fail "Git remote is not configured: ${REMOTE}"
CURRENT_BRANCH="$(git -C "${REPO_ROOT}" branch --show-current)"
[[ "${CURRENT_BRANCH}" == "${BRANCH}" ]] ||
  fail "Checkout is on '${CURRENT_BRANCH:-detached HEAD}', not '${BRANCH}'. Switch branches before installing."

if [[ -z "${RUN_USER}" ]]; then
  RUN_USER="${SUDO_USER:-$(stat -c '%U' "${REPO_ROOT}")}"
fi
id "${RUN_USER}" >/dev/null 2>&1 || fail "Linux user does not exist: ${RUN_USER}"
RUN_GROUP="$(id -gn "${RUN_USER}")"

for argument in "${DEPLOY_ARGUMENTS[@]}"; do
  [[ "${argument}" != *$'\n'* ]] || fail "Deployment arguments cannot contain newlines."
  [[ "${argument}" != "--follow-logs" ]] || fail "--follow-logs is not valid for an unattended service."
done

install -d -m 0755 "${CONFIG_DIR}" "${LIBEXEC_DIR}"
install -m 0755 "${SCRIPT_DIR}/auto-deploy-launcher.sh" "${LIBEXEC_DIR}/battery-auto-deploy-launcher"
printf '%s\n' "${REPO_ROOT}" > "${CONFIG_DIR}/${SERVICE}.repo"
printf '%s\n' "${BRANCH}" > "${CONFIG_DIR}/${SERVICE}.branch"
printf '%s\n' "${REMOTE}" > "${CONFIG_DIR}/${SERVICE}.remote"
if [[ "${#DEPLOY_ARGUMENTS[@]}" -gt 0 ]]; then
  printf '%s\n' "${DEPLOY_ARGUMENTS[@]}" > "${CONFIG_DIR}/${SERVICE}.args"
elif [[ ! -f "${CONFIG_DIR}/${SERVICE}.args" ]]; then
  : > "${CONFIG_DIR}/${SERVICE}.args"
fi
if [[ ! -f "${CONFIG_DIR}/${SERVICE}.env" ]]; then
  printf '%s\n' \
    '# Optional systemd environment entries, one NAME=value per line.' \
    '# Host-specific Docker Compose values may also remain in the repository .env file.' \
    > "${CONFIG_DIR}/${SERVICE}.env"
fi
chown root:"${RUN_GROUP}" "${CONFIG_DIR}/${SERVICE}.args" "${CONFIG_DIR}/${SERVICE}.env"
chmod 0640 "${CONFIG_DIR}/${SERVICE}.args" "${CONFIG_DIR}/${SERVICE}.env"

cat > "${service_path}" <<EOF
[Unit]
Description=${DESCRIPTION}
Wants=network-online.target docker.service
After=network-online.target docker.service

[Service]
Type=oneshot
User=${RUN_USER}
Group=${RUN_GROUP}
Environment=GIT_TERMINAL_PROMPT=0
Environment=AUTO_DEPLOY_STATE_DIR=/var/lib/battery-auto-deploy
EnvironmentFile=-${CONFIG_DIR}/${SERVICE}.env
ExecStart=${LIBEXEC_DIR}/battery-auto-deploy-launcher ${SERVICE}
StateDirectory=battery-auto-deploy
StateDirectoryMode=0750
UMask=0027
TimeoutStartSec=infinity
EOF

cat > "${timer_path}" <<EOF
[Unit]
Description=Check ${BRANCH} for ${DESCRIPTION} updates

[Timer]
OnBootSec=2min
OnUnitActiveSec=${INTERVAL}
RandomizedDelaySec=${RANDOM_DELAY}
AccuracySec=15s
Persistent=true
Unit=${UNIT_BASE}.service

[Install]
WantedBy=timers.target
EOF

chmod 0644 "${service_path}" "${timer_path}" \
  "${CONFIG_DIR}/${SERVICE}.repo" "${CONFIG_DIR}/${SERVICE}.branch" \
  "${CONFIG_DIR}/${SERVICE}.remote"
systemctl daemon-reload
systemctl enable --now "${UNIT_BASE}.timer"

printf '[battery-auto-deploy:installer] Installed %s.timer for %s/%s every %s.\n' \
  "${UNIT_BASE}" "${REMOTE}" "${BRANCH}" "${INTERVAL}"
if [[ "${RUN_NOW}" -eq 1 ]]; then
  printf '[battery-auto-deploy:installer] Running the first update check now...\n'
  systemctl start "${UNIT_BASE}.service"
fi
printf '[battery-auto-deploy:installer] View activity with: journalctl -u %s.service -f\n' "${UNIT_BASE}"
