#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
case "$SCRIPT_PATH" in
  */*) SCRIPT_DIR="$(cd -- "${SCRIPT_PATH%/*}" && pwd)" ;;
  *) SCRIPT_DIR="$(pwd)" ;;
esac
KIOSK_USER=battery-kiosk
CONFIG_DIR=/etc/battery-kiosk
STATE_DIR=/var/lib/battery-kiosk
LIGHTDM_CONFIG=/etc/lightdm/lightdm.conf.d/99-battery-kiosk.conf
SERVICE_CONFIG=/etc/systemd/system/lightdm.service.d/90-battery-kiosk.conf
URL=""
BROWSER=""
REFRESH_MINUTES=360
INSTALL_PACKAGES=1
START_NOW=0
ACTION=install

usage() {
  printf '%s\n' \
    'Install a local touchscreen kiosk without moving the monitor or collector.' \
    'Usage: sudo bash kiosk/install-kiosk.sh --url http://MONITOR-HOST:8080 [options]' \
    '  --browser PATH         Use an existing Chromium executable' \
    '  --refresh-minutes N    Reopen the dashboard periodically (default 360; 0 disables)' \
    '  --no-install-packages  Require dependencies to be installed already' \
    '  --start-now            Restart the local display after installation' \
    '  --status               Show kiosk, display, and recent browser logs' \
    '  --disable              Remove kiosk autologin; retain profile and packages' \
    '  -h, --help             Show help' \
    '' \
    'Default: configure next boot, without rebooting or restarting the collector.' \
    '--start-now logs out anyone using the local graphical display.'
}

fail() { printf '[battery-kiosk] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[battery-kiosk] %s\n' "$*"; }
need_value() { [[ $# -ge 2 && -n "$2" ]] || fail "$1 requires a value"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) need_value "$@"; URL="$2"; shift 2 ;;
    --browser) need_value "$@"; BROWSER="$2"; shift 2 ;;
    --refresh-minutes) need_value "$@"; REFRESH_MINUTES="$2"; shift 2 ;;
    --no-install-packages) INSTALL_PACKAGES=0; shift ;;
    --start-now) START_NOW=1; shift ;;
    --status) ACTION=status; shift ;;
    --disable) ACTION=disable; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

[[ "$(uname -s)" == Linux ]] || fail 'Run this installer on the Linux Raspberry Pi.'
[[ $EUID -eq 0 ]] || fail 'Run with sudo; Chromium itself will use a non-admin kiosk account.'
[[ -d /run/systemd/system ]] || fail 'A systemd host is required. Do not run inside Docker.'
exec 9>/run/lock/battery-kiosk-install.lock
flock -n 9 || fail 'Another kiosk installer is already running.'

if [[ "$ACTION" == status ]]; then
  systemctl status lightdm --no-pager || true
  loginctl list-sessions || true
  [[ ! -f "$CONFIG_DIR/config.json" ]] || cat "$CONFIG_DIR/config.json"
  journalctl -u lightdm -b --no-pager -n 25 || true
  tail -n 40 /home/battery-kiosk/.local/state/battery-kiosk/kiosk.log 2>/dev/null || true
  exit 0
fi

if [[ "$ACTION" == disable ]]; then
  [[ -f "$STATE_DIR/managed" ]] || fail 'No managed kiosk installation was found.'
  rm -f -- "$LIGHTDM_CONFIG" "$SERVICE_CONFIG"
  if [[ -f "$STATE_DIR/previous-target" ]]; then
    systemctl set-default "$(cat "$STATE_DIR/previous-target")"
  fi
  systemctl daemon-reload
  log 'Kiosk autologin disabled. The account, browser profile, and installed packages were retained.'
  if [[ $START_NOW -eq 1 ]]; then
    systemctl restart lightdm
  else
    log 'The existing kiosk stays visible until logout, display restart, or next reboot.'
  fi
  exit 0
fi

[[ -f "$SCRIPT_DIR/kiosk.py" && -f "$SCRIPT_DIR/openbox.xml" ]] || fail 'Keep the kiosk directory together.'
[[ -n "$URL" ]] || fail '--url must point to your x86_64 monitor, not the collector API.'
[[ "$REFRESH_MINUTES" =~ ^[0-9]+$ && ${#REFRESH_MINUTES} -le 5 ]] || fail 'Refresh minutes must be an integer from 0 to 99999.'
command -v python3 >/dev/null || fail 'Install python3 first.'
python3 "$SCRIPT_DIR/kiosk.py" --validate-url "$URL"
# LightDM's main file takes precedence over a matching section in a drop-in.
python3 - <<'PY'
import configparser
import sys

path = '/etc/lightdm/lightdm.conf'
config = configparser.ConfigParser(interpolation=None, strict=False)
config.read(path)
expected = {'autologin-user': 'battery-kiosk', 'autologin-user-timeout': '0',
            'autologin-session': 'battery-kiosk', 'user-session': 'battery-kiosk',
            'xserver-command': 'X -nocursor'}
if config.has_section('Seat:seat0'):
    for key, value in expected.items():
        if config.has_option('Seat:seat0', key) and config.get('Seat:seat0', key) != value:
            sys.exit(f'Conflicting {key} in {path} [Seat:seat0]. Back up and resolve it before installing; no desktop settings were overwritten.')
PY

if [[ -f /etc/X11/default-display-manager ]]; then
  manager="$(cat /etc/X11/default-display-manager)"
  [[ "$manager" == */lightdm ]] || fail "Another display manager is configured ($manager). Refusing to replace it automatically."
fi
for manager in gdm gdm3 sddm; do
  ! systemctl is-active --quiet "$manager" || fail "$manager is running. This installer requires LightDM."
done
if id "$KIOSK_USER" >/dev/null 2>&1 && [[ ! -f "$STATE_DIR/managed" ]]; then
  fail "The $KIOSK_USER account already exists and is not managed by this installer."
fi

if [[ $INSTALL_PACKAGES -eq 1 ]]; then
  log 'Installing the lightweight X11 session and touchscreen input support.'
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    lightdm lightdm-gtk-greeter openbox xserver-xorg xserver-xorg-input-libinput \
    x11-xserver-utils dbus-x11 python3 fonts-noto-core
fi
for dependency in lightdm openbox Xorg xset dbus-run-session; do
  command -v "$dependency" >/dev/null || fail "Missing dependency: $dependency"
done

if [[ -z "$BROWSER" ]]; then
  for candidate in chromium chromium-browser /snap/bin/chromium; do
    if command -v "$candidate" >/dev/null 2>&1; then
      BROWSER="$(command -v "$candidate")"
      break
    fi
  done
fi
if [[ -z "$BROWSER" && $INSTALL_PACKAGES -eq 1 ]]; then
  for package in chromium chromium-browser; do
    candidate="$(LC_ALL=C apt-cache policy "$package" | awk '/Candidate:/ {print $2; exit}')"
    if [[ -n "$candidate" && "$candidate" != '(none)' ]]; then
      DEBIAN_FRONTEND=noninteractive apt-get install -y "$package" ||
        fail 'Chromium installation failed. On Ubuntu this may require Snap Store access. Fix the package error, then rerun.'
      for executable in chromium chromium-browser /snap/bin/chromium; do
        if command -v "$executable" >/dev/null 2>&1; then BROWSER="$(command -v "$executable")"; break; fi
      done
      break
    fi
  done
fi
[[ "$BROWSER" == /* && -x "$BROWSER" ]] || fail 'Chromium was not found. Install it or supply --browser /absolute/path/to/chromium.'
"$BROWSER" --version || fail 'Chromium is installed but cannot start. Resolve its package/Snap error first.'

install -d -m 755 "$CONFIG_DIR" "$STATE_DIR" /usr/local/lib/battery-kiosk \
  /usr/share/xsessions /etc/lightdm/lightdm.conf.d /etc/systemd/system/lightdm.service.d
if [[ ! -f "$STATE_DIR/managed" ]]; then
  for path in "$LIGHTDM_CONFIG" "$SERVICE_CONFIG" /usr/share/xsessions/battery-kiosk.desktop; do
    [[ ! -e "$path" ]] || fail "Refusing to overwrite unmanaged file: $path"
  done
  systemctl get-default > "$STATE_DIR/previous-target"
  useradd --create-home --user-group --shell /bin/bash "$KIOSK_USER"
  touch "$STATE_DIR/managed"
fi
home="$(getent passwd "$KIOSK_USER" | cut -d: -f6)"
[[ "$home" == /home/battery-kiosk ]] || fail 'The kiosk account must use /home/battery-kiosk.'
# Some distributions gate LightDM passwordless login through this group.
if getent group autologin >/dev/null; then usermod -aG autologin "$KIOSK_USER"; fi
install -m 644 "$SCRIPT_DIR/kiosk.py" /usr/local/lib/battery-kiosk/kiosk.py
install -m 644 "$SCRIPT_DIR/openbox.xml" "$CONFIG_DIR/openbox.xml"
python3 /usr/local/lib/battery-kiosk/kiosk.py --write-config "$CONFIG_DIR/config.json" \
  --url "$URL" --browser "$BROWSER" --refresh-minutes "$REFRESH_MINUTES"
chmod 644 "$CONFIG_DIR/config.json"

cat > /usr/share/xsessions/battery-kiosk.desktop <<'EOF'
[Desktop Entry]
Name=Battery Kiosk
Comment=Dedicated battery dashboard display
Exec=/usr/bin/dbus-run-session -- /usr/bin/python3 /usr/local/lib/battery-kiosk/kiosk.py --run
Type=Application
DesktopNames=BatteryKiosk
EOF
cat > "$LIGHTDM_CONFIG" <<'EOF'
# Managed by Batteries Query Service kiosk/install-kiosk.sh
[Seat:seat0]
autologin-user=battery-kiosk
autologin-user-timeout=0
autologin-session=battery-kiosk
user-session=battery-kiosk
xserver-command=X -nocursor
EOF
cat > "$SERVICE_CONFIG" <<'EOF'
# Managed by Batteries Query Service kiosk/install-kiosk.sh
[Service]
Restart=always
RestartSec=5
EOF
systemctl daemon-reload
systemctl enable lightdm
systemctl set-default graphical.target
log "Installed. Display URL: $URL"
log 'The display will boot into the kiosk automatically. Docker and collector configuration were not changed.'
log 'Status: sudo bash kiosk/install-kiosk.sh --status'
log 'Disable: sudo bash kiosk/install-kiosk.sh --disable'
if [[ $START_NOW -eq 1 ]]; then
  log 'Restarting the local graphical display now; existing desktop sessions will close.'
  systemctl restart lightdm
else
  log 'Start when ready: sudo systemctl restart lightdm (closes local desktop sessions), or reboot during a maintenance window.'
fi
