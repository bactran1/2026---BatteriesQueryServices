# Batteries Query Service

A containerized polling service for Eco-worthy 48 V / 51.2 V server rack batteries.

The service talks to the battery BMS over a USB serial adapter, polls each configured pack address, and exposes the latest telemetry as JSON and Prometheus metrics.

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
2. Connect the Linux host to the battery communication port through a USB RS485 or RS232 adapter.
3. Pass that serial device into Docker, commonly `/dev/ttyUSB0` or a stable `/dev/serial/by-id/...` path.

## Quick start

```bash
docker compose up -d --build
```

Then check:

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/api/readings
curl http://localhost:8000/metrics
```

## Raspberry Pi 4B deployment

A Raspberry Pi 4B with 8 GB RAM is more than enough for this collector. Use Raspberry Pi OS Lite 64-bit if possible, install Docker Engine with the Compose plugin, and plug the USB-to-RS485 adapter into the Pi.

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

- `GET /healthz` - service health and polling status
- `GET /api/readings` - all configured batteries
- `GET /api/readings/{battery_id}` - one battery
- `GET /api/config` - safe runtime configuration
- `GET /metrics` - Prometheus exposition format

## Notes

- The service only reads status data. It does not send write/reset/control commands.
- If only the master battery responds, verify the DIP switch addresses and the communication port being used. Some firmware/port combinations expose only master-pack data.
- If Docker cannot open the serial device, check host permissions and confirm the `devices` mapping.
