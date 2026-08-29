# Renogy X 8K inverter telemetry

## Compatibility basis

The Renogy X 8K model `RIV4880HI-SPS` closely matches the Megarevo R8KLNA
platform in its enclosure, split-phase ratings, four MPPT inputs, 48 V battery
range, LCD, connector layout, and operating behavior. Megarevo's own R5-R10KLNA
[user manual](https://www.megarevo.com/upload/download/R5~R10KLNA%20series%20%28Colorscreen%29%20hybrid%20inverter%20user%20manual.pdf)
also matches the corresponding LNA manual included in this repository.

This is strong compatibility evidence, but it is not a published statement from
Renogy that Megarevo manufactured every Renogy X unit. The collector therefore
labels the driver `megarevo-r8klna-v2.12-read-only`, applies plausibility checks,
and keeps inverter failure independent from battery collection. Validate the
first live values against the inverter LCD.

The register implementation follows Megarevo's
[Hybrid Inverter Modbus Protocol V2.12](https://github.com/davidrapan/ha-solarman/discussions/883),
dated February 17, 2025. The included Renogy manuals do not contain this
register table.

## Connection

Use a second, preferably galvanically isolated, USB-to-RS485 adapter:

```text
Eco-worthy battery RS-485 bus
  -> battery USB-to-RS485 adapter
  -> Raspberry Pi host device /dev/serial/by-id/...
  -> collector container /dev/ttyUSB0

Renogy X host/EMS RS-485 port
  -> inverter USB-to-RS485 adapter
  -> Raspberry Pi host device /dev/serial/by-id/...
  -> collector container /dev/ttyUSB1
```

Use the inverter's dedicated host, meter, or EMS RS-485 connection. Do not
connect the collector to `BMS-485/BMS-CAN`, parallel CAN, CT, or Ethernet ports.
Confirm the actual A, B, and reference pins before making an RJ45 cable. An RJ45
connector does not imply Ethernet, and a BMS connector's pinout is not evidence
for the host RS-485 connector.

Modbus RTU should have only one active master. If the Wi-Fi logger or another
controller already polls the same RS-485 pair, use a separate host port or
disconnect the other master before enabling this collector.

## Serial settings

The V2.12 protocol specifies:

- Modbus RTU slave address 1 by default
- 9600 baud
- 8 data bits
- no parity
- 1 stop bit
- function `0x03` for telemetry reads

The permanent driver has no register-write method and never sends function
`0x06` or `0x10`.

## Raspberry Pi deployment

List both adapters and identify which physical adapter is connected to each
bus:

```bash
ls -l /dev/serial/by-id/
```

Deploy with both stable paths:

```bash
bash deploy-collector.sh \
  --serial-device /dev/serial/by-id/usb-Battery_RS485_Adapter \
  --inverter-serial-device /dev/serial/by-id/usb-Inverter_RS485_Adapter
```

The script maps the host paths to stable names inside the container. This
prevents the adapters from exchanging `/dev/ttyUSB0` and `/dev/ttyUSB1` after a
reboot. It also rejects a configuration where both arguments resolve to the
same device.

The inverter is configured in `config.toml`:

```toml
[inverter]
enabled = true
id = "renogy-x-8k"
model = "Renogy X 8K (Megarevo R8KLNA-compatible)"
serial_port = "/dev/ttyUSB1"
address = 1
baudrate = 9600
timeout_seconds = 2.0
parity = "N"
retries = 2
```

The environment equivalents use the `BQS_INVERTER_` prefix. For example,
`BQS_INVERTER_ADDRESS=2` overrides the TOML address.

## Telemetry

The collector polls the inverter on the same interval as the batteries and
returns direct, timestamped measurements for:

- PV1 through PV4 voltage, current, power, and total PV power
- Grid L1/L2 voltage, current, power, frequency, import, and export
- Backup load L1/L2 power and external home-load power
- Battery voltage, current, power, SOC, temperature, charge/discharge limits,
  and BMS cell extremes reported through the inverter
- Inverter L1/L2 voltage, current, power, bus voltage, leakage current, and
  inverter/internal/DC-DC temperatures
- Generator voltage and frequency
- Daily and lifetime PV, grid, load, battery charge, and battery discharge
  energy
- Decoded system, inverter, and DC-DC operating states
- Active DSP alarms and faults, plus raw DSP, ARM, and BMS words

Power direction follows the Megarevo table:

- `grid_total_power_w > 0`: exporting to the grid
- `grid_total_power_w < 0`: importing from the grid
- `battery_power_w > 0`: charging the battery
- `battery_power_w < 0`: discharging the battery

`grid_import_power_w` and `grid_export_power_w` are also returned as separate,
non-negative values. The monitor should animate grid flow only when these
direct inverter values are present; it should not infer grid flow from solar,
load, and battery power.

## API and health

Use either endpoint:

```bash
curl http://localhost:8000/api/inverter
curl http://localhost:8000/api/readings
```

The inverter object has one of four states:

- `ok`: all requested ranges were read
- `degraded`: core telemetry is valid but an optional range failed
- `error`: the adapter, wiring, address, baud rate, or register profile did not
  produce usable telemetry
- `disabled`: inverter collection is disabled

The last good inverter reading is preserved during a later error and is paired
with `last_success_at` and `last_error`. An inverter error does not stop battery
polling and does not make `/healthz` fail; inspect `inverter_status` there.

Prometheus metrics use the `inverter_` prefix, including PV, grid import/export,
load, home load, battery power/SOC, temperatures, per-MPPT values, poll success,
and optional range errors.

The x86 monitor already forwards the inverter object inside its live snapshot,
but its dashboard views and three-year SQLite schema remain battery-specific.
Those can consume this collector contract in a separate monitor update.

## First-run validation

Compare all of the following with the LCD while values are changing:

1. PV1-PV4 voltage and total PV power.
2. Grid L1/L2 voltage and import/export direction.
3. Backup load and home-load power, noting which circuits the inverter meters.
4. Battery voltage, SOC, and charge/discharge direction.
5. Inverter and DC-DC temperatures.

If the values are absent or implausible, verify A/B polarity, port pinout, slave
address, and baud rate before assuming a register problem. The optional
`renogy-x-probe` command remains available for read-only raw register diagnosis;
do not write settings while identifying an unknown firmware variant.
