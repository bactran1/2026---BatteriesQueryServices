# Raspberry Pi Touchscreen Kiosk

This turns a Raspberry Pi into a local, full-screen viewer for the existing monitor.
The monitor container and three-year SQLite archive stay on the x86_64 host.
The collector and its Docker configuration are not changed. Installation can be
run over SSH; no manually assigned `DISPLAY`, X authority file, or SSH forwarding
is needed.

## Install

Use the existing Ubuntu 22.04 or Debian/Raspberry Pi OS installation. Do not
reflash a working collector's SD card. The Pi needs a working, connected display,
network access to the monitor, and root access for installation. A new lightweight
X11/Openbox session is installed, so a pre-existing desktop is not required.
LightDM is supported; the installer refuses to replace another display manager.

From the repository root **on the Pi, outside Docker**:

```bash
sudo bash kiosk/install-kiosk.sh --url http://YOUR-MONITOR-HOST:8080
```

Replace `YOUR-MONITOR-HOST` with the x86_64 monitor host's LAN name or IP address.
Use the dashboard URL, not the collector's port 8000. Keep all files in this
`kiosk` directory together. The installer copies its runtime files into the host;
the checkout does not have to remain at its original path afterward.

By default, the installer configures automatic startup for the next boot. To
activate it immediately without rebooting the collector Pi:

```bash
sudo bash kiosk/install-kiosk.sh --url http://YOUR-MONITOR-HOST:8080 --start-now
```

**`--start-now` restarts LightDM and closes all local graphical sessions.** It does
not restart Docker or the collector. Installing missing display packages may
also start the display manager as part of package installation. Use a maintenance
window if someone is using the local desktop.

The script uses an existing `chromium`, `chromium-browser`, or `/snap/bin/chromium`.
If none exists, it tries the browser package available in your OS repositories.
Ubuntu's Chromium package may require Snap Store access. Package installation
failures are reported rather than bypassed with untrusted repositories.

Options:

```bash
# Pin the already-working executable.
sudo bash kiosk/install-kiosk.sh --url http://YOUR-MONITOR-HOST:8080 --browser /usr/bin/chromium

# Require dependencies to be installed already.
sudo bash kiosk/install-kiosk.sh --url http://YOUR-MONITOR-HOST:8080 --no-install-packages

# Disable the default six-hour browser refresh.
sudo bash kiosk/install-kiosk.sh --url http://YOUR-MONITOR-HOST:8080 --refresh-minutes 0
```

## Everyday Operation

- LightDM starts at boot and automatically logs the separate `battery-kiosk`
  account into a dedicated session on the primary local seat.
- The session supplies the correct display permissions and D-Bus environment.
  Chromium runs as an ordinary user with its sandbox and GPU acceleration intact.
- No desktop panel, mouse cursor, window decorations, or Openbox launcher shortcuts
  are exposed. The screen stays awake. Touch input is handled through libinput.
- A local connection screen appears if the monitor cannot be reached. The runtime
  checks the dashboard URL approximately every ten seconds with a five-second
  timeout. Three consecutive failures switch to the connection screen; a successful
  check reopens the dashboard. Brief outages retain the page's own stale-data view.
- Closing Chromium or a browser process exit triggers relaunch with bounded retry
  delays. A hung process that does not exit is not independently detected.
- Every six hours, Chromium is reopened to pick up deployed frontend changes and
  reset its long-running process. This also returns the page to its initial view.
- Language/theme preferences persist in a separate browser profile. No browser
  profile from your normal account is modified.
- The connection check targets the monitor page, not collector health. If the
  collector is offline but the monitor is available, its outage remains visible.

This is a kiosk presentation, not a hardened public terminal. Keep it on the
trusted LAN, protect physical ports, and retain SSH access for maintenance. Do not
sign into the monitor's admin console in the kiosk profile. Anyone with physical
access can interact with the displayed dashboard.

## Manage and Troubleshoot

```bash
sudo bash kiosk/install-kiosk.sh --status
sudo journalctl -u lightdm -b --no-pager -n 80
sudo tail -n 80 /var/log/lightdm/lightdm.log /var/log/lightdm/x-0.log
sudo tail -n 80 /home/battery-kiosk/.local/state/battery-kiosk/kiosk.log
```

The runtime logs browser errors and rotates its log at 2 MB with three backups.
If no runtime log exists, LightDM probably has not started the kiosk session yet.
Check its logs for a missing graphics device, display driver, or conflicting
LightDM settings. `sudo lightdm --show-config` lists the effective configuration
and its source files; an explicit `[Seat:seat0]` in `/etc/lightdm/lightdm.conf`
can override the kiosk drop-in. Existing display configuration is preserved.

The installer cannot fix unsupported touchscreen hardware, unplugged display
cables, rotation/touch calibration, or an incorrectly configured graphics driver.
It does not change GPU firmware configuration, display resolution, or orientation.
The existing Three.js scene is used unchanged; smoothness must be checked on the
actual Pi/display, particularly at high resolutions.

Rerun the installer with the new URL or latest checkout to update the installation.
Use `--start-now` to apply changes immediately, otherwise they apply next session.

```bash
sudo bash kiosk/install-kiosk.sh --disable
```

This removes the managed autologin/service overrides and restores the previous
boot target. It leaves the kiosk account, profile, runtime, and packages installed.
The current screen remains until logout or reboot; add `--start-now` to restart
the display immediately. Existing LightDM settings then take effect again.

Installed locations:

| Purpose | Location |
| --- | --- |
| URL, browser, refresh interval | `/etc/battery-kiosk/config.json` |
| Session runtime | `/usr/local/lib/battery-kiosk/kiosk.py` |
| Window manager settings | `/etc/battery-kiosk/openbox.xml` |
| Session entry | `/usr/share/xsessions/battery-kiosk.desktop` |
| Local-seat autologin | `/etc/lightdm/lightdm.conf.d/99-battery-kiosk.conf` |
| Display-manager restart policy | `/etc/systemd/system/lightdm.service.d/90-battery-kiosk.conf` |
| Install marker and original boot target | `/var/lib/battery-kiosk/` |
| Browser profile | `/home/battery-kiosk/snap/chromium/common/battery-kiosk-profile/` |

References: [LightDM configuration](https://github.com/canonical/lightdm/blob/main/data/lightdm.conf),
[Ubuntu Chromium packaging](https://packages.ubuntu.com/jammy/chromium-browser),
[Chromium display backends](https://chromium.googlesource.com/chromium/src/+/main/docs/ozone_overview.md).
