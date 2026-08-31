# Batteries Query Service

A containerized polling service for Eco-worthy 48 V / 51.2 V server rack
batteries and a Renogy X 8K hybrid inverter.

The collector uses one USB-to-RS485 adapter for the battery bus and reads the
inverter through its installed SOLARMAN LSW-5 Wi-Fi logger on local TCP port
8899. A second USB-to-RS485 adapter remains supported as a fallback. The
collector exposes the latest telemetry as JSON and Prometheus metrics and keeps
a rolling replay buffer on the Raspberry Pi. A companion monitor app runs on a
separate x86_64 Docker host, stores the battery telemetry for three years, and
serves a local dashboard.

The inverter driver is read-only and implements the Megarevo R8KLNA Modbus
V2.12 telemetry profile that matches the Renogy X hardware and manuals. Because
Renogy does not publish an explicit OEM declaration or model-specific register
map, compare the first readings with the inverter LCD before relying on them.
See [Renogy X inverter telemetry](docs/renogy-x-telemetry.md).

## What it reads

- Pack voltage, current, power, SOC, SOH, and capacity
- Cell voltages, min/max/average cell voltage, and cell delta
- Battery temperatures
- Charge and discharge limits
- MOSFET state, operating state, alarms, faults, firmware, serial number, and known parallel pack addresses when reported by the BMS
- Inverter PV1-PV4 voltage, current, power, and total solar power
- Grid import/export, L1/L2 voltage/current/power, frequency, backup load, and measured home load
- Inverter-side battery voltage/current/power/SOC, temperatures, operating state, alarms, faults, and energy counters

## Hardware assumptions

This first driver targets Eco-worthy/JBD-UP style Modbus RTU frames at 9600 baud. Eco-worthy documentation lists RS485-1 for host computer/inverter access and RS232 for host computer access; their protocol table lists PYLON-LV on RS485-1 and JBD-UP/Solar Assistant/Overkill on RS232.

For three rack batteries and the inverter, the usual deployment is:

1. Set the battery DIP switches so the packs have addresses 1, 2, and 3.
2. Connect the Raspberry Pi to the battery communication port through the first USB RS485 or RS232 adapter.
3. Leave the SOLARMAN LSW-5 installed, give it a stable DHCP reservation, and
   confirm the Raspberry Pi can reach its LAN address on TCP port 8899.
4. Record the serial number printed on the logger. This is not the inverter
   serial number and is required by the SOLARMAN V5 protocol.
5. Map the battery adapter's stable `/dev/serial/by-id/...` host path into the
   Pi collector container.
6. Point the x86_64 monitor container at the Pi collector URL.

## Quick start

On the Raspberry Pi collector host, supply the LSW-5 address and printed logger
serial while deploying (or put the same values in `config.toml`):

```bash
bash deploy-collector.sh \
  --inverter-host 192.168.10.50 \
  --inverter-logger-serial 1234567890
```

Then check:

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/api/readings
curl http://localhost:8000/metrics
```

On the x86_64 monitor host, set the collector URL to the Pi hostname or IP address:

```bash
export BQM_COLLECTOR_URL=http://raspberrypi.local:8000
docker compose -f docker-compose.monitor.yml up -d --build
```

Open the monitor dashboard from your browser:

```bash
http://x86-monitor-hostname:8080
```

Replace `x86-monitor-hostname` with the x86_64 host name or IP address.

## Monitor app

The `battery-monitor` container runs on the dedicated x86_64 Linux Docker host. It polls the Pi collector at `${BQM_COLLECTOR_URL}/api/readings`, logs each battery snapshot to SQLite, and serves the dashboard on port `8080`.

Defaults:

- Live collector refresh: 5 seconds, shared by every dashboard browser
- Log interval: 60 seconds
- Retention: 1095 days, approximately 3 years
- Storage path on the x86_64 host: `./data/monitor/battery-monitor.sqlite3`
- CSV export: dashboard download button or `GET /api/export.csv`

The monitor owns one collector connection and serves a cached live snapshot to every browser. Opening more dashboard tabs does not create more requests to the Raspberry Pi. The dashboard refreshes live values every 5 seconds, pauses network work while its tab is hidden, and refreshes immediately when the tab becomes visible again.

Dashboard HTML is always served with `no-store`. JavaScript, CSS, icons, and logos use a content fingerprint and immutable caching, so a normal reload after deployment picks up the new build without requiring a hard refresh.

Connection states are explicit: `online` means every active battery is responding, `degraded` means the collector is reachable but at least one battery is not healthy, `stale` means last-known data is being shown during recovery, and `offline` means the collector has exceeded the configured outage threshold.

Environment overrides:

- `BQM_COLLECTOR_URL`
- `BQM_COLLECTOR_TIMEOUT_SECONDS`
- `BQM_LIVE_POLL_INTERVAL_SECONDS`
- `BQM_STALE_AFTER_SECONDS`
- `BQM_OFFLINE_AFTER_SECONDS`
- `BQM_BACKFILL_PAGE_SIZE`
- `BQM_RACK_NAME`, returned with rack metadata by the monitor API
- `BQM_RACK_BUILDER`
- `BQM_RACK_LOCATION`
- `BQM_COLLECTOR_NAME`
- `BQM_BATTERY_IDS`
- `BQM_BATTERY_ADDRESSES`
- `BQM_BATTERY_NAMES`
- `BQM_BATTERY_IPS`
- `BQM_BATTERY_MODELS`
- `BQM_DATA_DIR`
- `BQM_DATABASE_PATH`
- `BQM_LOG_INTERVAL_SECONDS`
- `BQM_RETENTION_DAYS`
- `BQM_HOST`
- `BQM_PORT`
- `BQM_LOG_LEVEL`

The dashboard defaults to three rack batteries and shows the rack builder as Tran Thanh Tuan. Set the inventory values as comma-separated lists before deployment to show your actual names and addresses:

```bash
export BQM_BATTERY_NAMES="Top Battery,Middle Battery,Bottom Battery"
export BQM_BATTERY_IPS="192.168.1.61,192.168.1.62,192.168.1.63"
export BQM_BATTERY_MODELS="Eco-worthy 48V 100Ah,Eco-worthy 48V 100Ah,Eco-worthy 48V 100Ah"
bash monitor/deploy-monitor.sh --collector-url http://raspberrypi.local:8000
```

The IP addresses are inventory labels. Telemetry still travels from the batteries to the Raspberry Pi over RS485, then from the Pi to the monitor over the network. Leave an IP position empty when a battery does not have a directly reachable address, for example `BQM_BATTERY_IPS=192.168.1.61,,192.168.1.63`.

For repeatable deployments, start with `.env.example`, put the real values in a root-level `.env` file on the x86_64 host, and run the deployment script normally. Docker Compose loads that file automatically, and `.env` is excluded from Git so host-specific addresses are not committed.

At the default 60-second interval, three batteries produce roughly 4.7 million log rows across 3 years. The dashboard stores the raw reading payload for each row so cell voltages, temperatures, alarms, faults, limits, and pack metadata remain available.

The Pi collector stores one sequenced replay snapshot every 60 seconds for 24 hours at `./data/collector/collector-buffer.sqlite3`. When the monitor restarts or temporarily loses the Pi, it requests every missing sequence and inserts it idempotently. This repairs short archive gaps without changing the normal 60-second sampling rate or duplicating rows.

## Raspberry Pi 4B deployment

A Raspberry Pi 4B with 8 GB RAM is more than enough for the collector. Use Raspberry Pi OS Lite 64-bit if possible, install Docker Engine with the Compose plugin, and plug the battery USB-to-RS485 adapter into the Pi. The monitor/dashboard does not run on the Pi.

On the Pi, identify the battery adapter:

```bash
ls -l /dev/serial/by-id/
```

Prefer its stable path over `/dev/ttyUSB0`. Configure the LSW-5 LAN address and
printed logger serial in `config.toml`, then pass the battery adapter path to
the deployment script:

```bash
bash deploy-collector.sh \
  --serial-device /dev/serial/by-id/usb-Battery_RS485_Adapter
```

Allow your Pi user to run Docker and access serial devices:

```bash
sudo usermod -aG docker,dialout $USER
sudo reboot
```

After reboot:

```bash
bash deploy-collector.sh \
  --serial-device /dev/serial/by-id/usb-Battery_RS485_Adapter
```

The script fetches and fast-forwards to the latest Git commit, tags the image
with that commit SHA, pulls the latest base image, and performs a no-cache build
by default. If `batteries-query-service` does not exist, it creates it. If it
already exists, it replaces and restarts it with the newly built image. The
script then waits for the collector health check. The LSW-5 connection is made
from inside the container over the normal Docker bridge network; no host network
mode or second inverter USB device is required. A logger outage leaves battery
collection running and exposes the inverter with `status: "error"`; polling
automatically retries on the next interval.

Use the current checkout without fetching Git when developing locally:

```bash
bash deploy-collector.sh --skip-git-update
```

Allow Docker layer caching only when you intentionally want a faster build:

```bash
bash deploy-collector.sh --use-cache
```

Follow the collector logs after a successful deployment:

```bash
bash deploy-collector.sh --follow-logs
```

Then verify the collector from the Pi:

```bash
curl http://localhost:8000/api/readings
```

The x86_64 monitor host must be able to reach the Pi at `http://raspberrypi.local:8000` or at the Pi's static IP address.

## x86_64 monitor host deployment

Deploy the dashboard/logger on the dedicated x86_64 Linux Docker host.

If the x86 host can resolve the Pi hostname:

```bash
export BQM_COLLECTOR_URL=http://raspberrypi.local:8000
docker compose -f docker-compose.monitor.yml up -d --build
```

If it cannot, use the Pi IP address:

```bash
export BQM_COLLECTOR_URL=http://192.168.1.50:8000
docker compose -f docker-compose.monitor.yml up -d --build
```

Open:

```bash
http://x86-monitor-hostname:8080
```

To rebuild and restart the monitor after updates, use the helper script:

```bash
bash monitor/deploy-monitor.sh --collector-url http://raspberrypi.local:8000
```

The script builds the monitor image from `monitor/Dockerfile`. If no `battery-monitor` container exists, it creates one. If the container already exists, it updates it with the new image. In both cases, it keeps the existing `./data/monitor` log database and waits for the container health check.

By default, the script updates the local Git checkout to the latest remote commit before building. It tags the Docker image with that commit SHA, passes the SHA into the image metadata, rebuilds without Docker cache, and restarts the container from that image. Use this when deploying normal updates:

```bash
bash monitor/deploy-monitor.sh --collector-url http://raspberrypi.local:8000
```

If you intentionally want to build whatever files are currently on disk without pulling Git first:

```bash
bash monitor/deploy-monitor.sh --skip-git-update
```

If you want a faster cached build:

```bash
bash monitor/deploy-monitor.sh --use-cache
```

If Docker fails with `net.ipv4.ip_unprivileged_port_start` permission errors, the x86_64 Docker host cannot start containers correctly. This is usually seen when Docker is running inside an unprivileged LXC/Incus/Proxmox container, or when a host update introduced a runc/containerd/AppArmor incompatibility. Confirm with:

```bash
docker run --rm hello-world
```

If `hello-world` fails the same way, fix the Docker host before redeploying the monitor. Typical fixes are updating the LXC/Proxmox/Incus host packages, using a VM or bare-metal Docker host instead of Docker-inside-unprivileged-LXC, or temporarily rolling back the affected `containerd.io` package when that is the known source on your distribution.

## Configuration

Edit `config.toml` before starting the container. `config.example.toml` is kept as a clean reference copy.

```toml
[serial]
port = "/dev/ttyUSB0"
baudrate = 9600
timeout_seconds = 2.0

[polling]
interval_seconds = 10

[inverter]
enabled = true
id = "renogy-x-8k"
model = "Renogy X 8K (Megarevo R8KLNA-compatible)"
transport = "solarman_v5"
host = "192.168.10.50"       # LSW-5 LAN address or reserved hostname
tcp_port = 8899
logger_serial = 1234567890    # number printed on the LSW-5, not the inverter
address = 1
timeout_seconds = 2.0
retries = 2

[[batteries]]
id = "rack-1"
address = 1

[[batteries]]
id = "rack-2"
address = 2

[[batteries]]
id = "rack-3"
address = 3
```

Environment overrides are also supported:

- `BQS_CONFIG`
- `BQS_SERIAL_PORT`
- `BQS_INVERTER_ENABLED`
- `BQS_INVERTER_ID`
- `BQS_INVERTER_MODEL`
- `BQS_INVERTER_TRANSPORT`, `serial` or `solarman_v5`
- `BQS_INVERTER_HOST`
- `BQS_INVERTER_TCP_PORT`
- `BQS_INVERTER_LOGGER_SERIAL`
- `BQS_INVERTER_V5_ERROR_CORRECTION`
- `BQS_INVERTER_SERIAL_PORT`
- `BQS_INVERTER_ADDRESS`
- `BQS_INVERTER_BAUDRATE`
- `BQS_INVERTER_TIMEOUT_SECONDS`
- `BQS_INVERTER_PARITY`
- `BQS_INVERTER_RETRIES`
- `BQS_BATTERY_ADDRESSES`, for example `1,2,3`
- `BQS_BATTERY_IDS`, for example `rack-1,rack-2,rack-3`
- `BQS_POLL_INTERVAL`
- `BQS_BUFFER_ENABLED`
- `BQS_BUFFER_PATH`
- `BQS_BUFFER_RETENTION_HOURS`
- `BQS_BUFFER_SAMPLE_INTERVAL`
- `BQS_HOST`
- `BQS_PORT`
- `BQS_LOG_LEVEL`
- `BQS_BUILD_COMMIT`, set automatically by `deploy-collector.sh`

For the optional direct RS-485 fallback, use `transport = "serial"` and set
`serial_port`, `baudrate`, and `parity` as shown in `config.example.toml`.

## Docker serial devices

In LSW-5 mode, only the battery adapter needs to be mapped:

```bash
bash deploy-collector.sh \
  --serial-device /dev/ttyUSB0
```

For long-running systems, prefer a stable device path. Logger settings may be
kept in `config.toml` or supplied directly during deployment:

```bash
bash deploy-collector.sh \
  --serial-device /dev/serial/by-id/usb-Battery_RS485_Adapter \
  --inverter-host 192.168.10.50 \
  --inverter-logger-serial 1234567890
```

The serial fallback still accepts `--inverter-serial-device` and maps that
adapter to `/dev/ttyUSB1` in the container.

The same settings can be supplied as `COLLECTOR_SERIAL_DEVICE`,
`COLLECTOR_INVERTER_SERIAL_DEVICE`, and `COLLECTOR_CONFIG_FILE`. The running
image name and build revision are available from
`docker inspect batteries-query-service` and `GET /healthz`.

## API

Collector:

- `GET /healthz` - service health and polling status
- `GET /api/readings` - all configured batteries plus inverter state
- `GET /api/readings/history` - sequenced replay snapshots for monitor backfill
- `GET /api/readings/{battery_id}` - one battery
- `GET /api/inverter` - Renogy X inverter state and latest telemetry
- `GET /api/config` - safe runtime configuration
- `GET /metrics` - Prometheus exposition format

Monitor:

- `GET /` - dashboard
- `GET /healthz` - monitor health
- `GET /api/live` - cached collector snapshot with connection state and archive stats
- `GET /api/history` - chart history
- `GET /api/events` - recent alarms, faults, and collector errors
- `GET /api/export.csv` - CSV export

## Notes

- The service only reads status data. It does not send write/reset/control commands.
- Megarevo grid power is positive for export and negative for import. Battery current and power are positive while charging and negative while discharging.
- The monitor health response reports database health separately from collector connectivity. A collector outage does not make the dashboard container unhealthy; a database failure does.
- If only the master battery responds, verify the DIP switch addresses and the communication port being used. Some firmware/port combinations expose only master-pack data.
- If Docker cannot open the serial device, check host permissions and confirm the `devices` mapping.
