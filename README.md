# Batteries Query Service

A containerized polling service for Eco-worthy 48 V / 51.2 V server rack batteries.

The collector talks to the battery BMS over a USB serial adapter, polls each configured pack address, and exposes the latest telemetry as JSON and Prometheus metrics. A companion monitor app runs on a separate x86_64 Docker host, stores the telemetry for three years, and serves a local dashboard.

## What it reads

- Pack voltage, current, power, SOC, SOH, and capacity
- Cell voltages, min/max/average cell voltage, and cell delta
- Battery temperatures
- Charge and discharge limits
- MOSFET state, operating state, alarms, faults, firmware, serial number, and known parallel pack addresses when reported by the BMS

## Hardware assumptions

This first driver targets Eco-worthy/JBD-UP style Modbus RTU frames at 9600 baud. Eco-worthy documentation lists RS485-1 for host computer/inverter access and RS232 for host computer access; their protocol table lists PYLON-LV on RS485-1 and JBD-UP/Solar Assistant/Overkill on RS232.

For three rack batteries, the usual deployment is:

1. Set the battery DIP switches so the packs have addresses 1, 2, and 3.
2. Connect the Raspberry Pi to the battery communication port through a USB RS485 or RS232 adapter.
3. Pass that serial device into the Pi collector container, commonly `/dev/ttyUSB0` or a stable `/dev/serial/by-id/...` path.
4. Point the x86_64 monitor container at the Pi collector URL.

## Quick start

On the Raspberry Pi collector host:

```bash
docker compose up -d --build
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

- Log interval: 60 seconds
- Retention: 1095 days, approximately 3 years
- Storage path on the x86_64 host: `./data/monitor/battery-monitor.sqlite3`
- CSV export: dashboard download button or `GET /api/export.csv`

Environment overrides:

- `BQM_COLLECTOR_URL`
- `BQM_DATA_DIR`
- `BQM_DATABASE_PATH`
- `BQM_LOG_INTERVAL_SECONDS`
- `BQM_RETENTION_DAYS`
- `BQM_HOST`
- `BQM_PORT`
- `BQM_LOG_LEVEL`

At the default 60-second interval, three batteries produce roughly 4.7 million log rows across 3 years. The dashboard stores the raw reading payload for each row so cell voltages, temperatures, alarms, faults, limits, and pack metadata remain available.

## Raspberry Pi 4B deployment

A Raspberry Pi 4B with 8 GB RAM is more than enough for the collector. Use Raspberry Pi OS Lite 64-bit if possible, install Docker Engine with the Compose plugin, and plug the USB-to-RS485 adapter into the Pi. The monitor/dashboard does not run on the Pi.

On the Pi, identify the adapter:

```bash
ls -l /dev/serial/by-id/
```

If a stable adapter path is listed, prefer that over `/dev/ttyUSB0`. Update `docker-compose.yml`:

```yaml
devices:
  - "/dev/serial/by-id/usb-Your_Adapter:/dev/ttyBMS0"
```

Then update `config.toml`:

```toml
[serial]
port = "/dev/ttyBMS0"
baudrate = 9600
timeout_seconds = 2.0
```

Allow your Pi user to run Docker and access serial devices:

```bash
sudo usermod -aG docker,dialout $USER
sudo reboot
```

After reboot:

```bash
docker compose up -d --build
docker compose logs -f
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

## Configuration

Edit `config.toml` before starting the container. `config.example.toml` is kept as a clean reference copy.

```toml
[serial]
port = "/dev/ttyUSB0"
baudrate = 9600
timeout_seconds = 2.0

[polling]
interval_seconds = 10

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
- `BQS_BATTERY_ADDRESSES`, for example `1,2,3`
- `BQS_BATTERY_IDS`, for example `rack-1,rack-2,rack-3`
- `BQS_POLL_INTERVAL`
- `BQS_HOST`
- `BQS_PORT`
- `BQS_LOG_LEVEL`

## Docker serial device

The included compose file maps `/dev/ttyUSB0` into the container. If your adapter appears under another path, update this line:

```yaml
devices:
  - "/dev/ttyUSB0:/dev/ttyUSB0"
```

For long-running systems, prefer a stable device path:

```yaml
devices:
  - "/dev/serial/by-id/usb-Your_Adapter:/dev/ttyBMS0"
```

Then set `serial.port = "/dev/ttyBMS0"` in `config.toml`.

## API

Collector:

- `GET /healthz` - service health and polling status
- `GET /api/readings` - all configured batteries
- `GET /api/readings/{battery_id}` - one battery
- `GET /api/config` - safe runtime configuration
- `GET /metrics` - Prometheus exposition format

Monitor:

- `GET /` - dashboard
- `GET /healthz` - monitor health
- `GET /api/live` - live collector snapshot with archive stats
- `GET /api/history` - chart history
- `GET /api/events` - recent alarms, faults, and collector errors
- `GET /api/export.csv` - CSV export

## Notes

- The service only reads status data. It does not send write/reset/control commands.
- If only the master battery responds, verify the DIP switch addresses and the communication port being used. Some firmware/port combinations expose only master-pack data.
- If Docker cannot open the serial device, check host permissions and confirm the `devices` mapping.
