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

The preferred path keeps the supplied Wi-Fi logger installed:

```text
Eco-worthy battery RS-485 bus
  -> battery USB-to-RS485 adapter
  -> Raspberry Pi host device /dev/serial/by-id/...
  -> collector container /dev/ttyUSB0

Renogy X external COM port
  -> installed SOLARMAN LSW-5 logger
  -> local Wi-Fi/LAN, TCP 8899
  -> Raspberry Pi collector container
```

Use the external `COM` connection normally occupied by the Wi-Fi logger. The
included Renogy X manual confirms that this logger connection carries inverter
monitoring and configuration data. The supplied logger is an IGEN
Tech/SOLARMAN LSW-5, FCC ID `2A4FRLSW-5`. The logger's open TCP port 8899
provides SOLARMAN V5 framing around read-only Modbus RTU requests. The collector
uses the maintained
[`pysolarmanv5`](https://github.com/jmccrohan/pysolarmanv5) implementation and
requires both the logger's LAN address and the serial number printed on the
logger. The logger serial is not the inverter serial number.

Give the LSW-5 a DHCP reservation so its address remains stable. The Raspberry
Pi container only needs normal routed access to the logger; no host networking
or inbound port forwarding is required. Keep TCP 8899 limited to the trusted
local network.

Direct RS-485 remains available as a fallback. Disconnect the logger before
connecting a second, preferably isolated, USB-to-RS485 adapter to the same COM
pair. The LSW-5
[datasheet](https://cdn1.idek.cz/argos_cz/document/1095388486-lsw-5-wifi-dongle-datasheet)
defines the female aviation connector as pin 1 VCC, pin 2 GND, pin 3 RS485 A,
and pin 4 RS485 B. Connect the USB adapter to pins 3 and 4, optionally connect
signal ground to pin 2 if the adapter requires a reference, and never connect
pin 1 VCC to the USB adapter.

The physical connector appears to be the four-contact Exceedconn EC04681
family commonly used by LSW-5 inverter loggers, not an M10 or M12 D-coded
connector. A likely mating cable-end part is `EC04681-2023-BF`, but verify its
key, contact gender, and pin numbering against the supplied logger before
ordering or soldering it. Do not trust prewired cable colors without a
continuity check because the same shell is used with different pin assignments.

Do not connect the collector to the interior meter RS-485, `BMS-485/BMS-CAN`,
parallel CAN, CT, or Ethernet ports. The meter connection is a separate bus on
which the inverter communicates with its external utility meter; it is not the
telemetry connection used by the Wi-Fi logger.

Modbus RTU should have only one active master. If the Wi-Fi logger or another
controller already polls the COM RS-485 pair, do not attach a direct USB master
at the same time. In SOLARMAN V5 mode the LSW-5 remains the only physical
RS-485 master and relays the collector's requests.

## Protocol settings

The V2.12 protocol specifies:

- Modbus RTU slave address 1 by default
- 9600 baud
- 8 data bits
- no parity
- 1 stop bit
- function `0x03` for telemetry reads

The permanent driver has no register-write method and never sends function
`0x06` or `0x10`.

## Finding a setting's register

The work mode (SELFCONSUME / PEAK SHIFT / BAT PRIORITY) is set from the LCD
under `SYS SETTING > SETUP > WORK MODE`, and Megarevo's V2.12 register table is
not part of this repository, so the register behind it is unknown. The probe can
find it without writing anything: snapshot the settings registers, change the
mode on the panel, snapshot again, and see what moved.

A single read before and after does not work. The inverter keeps running, so
power, voltage, temperature and the energy counters all differ between any two
reads and bury the one register that matters. Each snapshot therefore samples
the same range several times and sorts registers into two groups: **stable**,
holding one value across every sample, and **volatile**, moving on their own.
A register is only reported as a candidate when it was stable before the
change, stable after it, readable on both sides, and holds a different value.

Take the baseline with the inverter in its current mode:

```bash
renogy-x-probe snapshot --active \
  --transport solarman --host 192.168.20.138 --logger-serial 3503566593 \
  --label SELFCONSUME --out /tmp/selfconsume.json
```

Change the mode on the LCD, then compare:

```bash
renogy-x-probe compare --active \
  --transport solarman --host 192.168.20.138 --logger-serial 3503566593 \
  --label "BAT PRIORITY" --baseline /tmp/selfconsume.json
```

Use `--transport serial --port /dev/ttyUSB1` instead for a direct RS-485 link.

The default ranges are `0x1000:0x13FF` and `0x2000:0x20FF`, chosen because the
protocol version and serial number answer from `0x1219` and `0x1234` while the
telemetry this service reads sits at `0x3100+`. Widen with `--range` if nothing
turns up; reading an unmapped address is harmless and answers `0xFFFF`.

Expect one candidate. If several registers changed, run it again switching back
to the original mode: the work-mode register is the one that returns to its
first value, and anything still drifting is not it. Confirm by switching a third
time and reading the register back.

Both commands read only. They inherit the same `--active` acknowledgement as the
rest of the probe, and neither they nor any module they use can send function
`0x06` or `0x10`.

**Do not write a register discovered this way without the vendor's register
table.** This inverter is certified to IEEE 1547 and Rule 21; a write to a
misidentified address could land on grid-protection, export or charge-limit
settings. Discovery tells you where the value lives, not that writing it is
safe.

## Raspberry Pi deployment

List the battery adapter and identify its stable host path:

```bash
ls -l /dev/serial/by-id/
```

Deploy with that stable path after configuring the logger:

```bash
bash deploy-collector.sh \
  --serial-device /dev/serial/by-id/usb-Battery_RS485_Adapter \
  --inverter-host 192.168.10.50 \
  --inverter-logger-serial 1234567890
```

Replace the sample host and serial with the LSW-5 values. The command-line
values override TOML for that deployment and the script does not require an
inverter USB device in this mode.

The inverter is configured in `config.toml`:

```toml
[inverter]
enabled = true
id = "renogy-x-8k"
model = "Renogy X 8K (Megarevo R8KLNA-compatible)"
transport = "solarman_v5"
host = "192.168.10.50"
tcp_port = 8899
logger_serial = 1234567890
address = 1
timeout_seconds = 2.0
retries = 2
```

The environment equivalents use the `BQS_INVERTER_` prefix. For example,
`BQS_INVERTER_HOST=192.168.10.50` overrides the TOML host. Set
`BQS_INVERTER_V5_ERROR_CORRECTION=true` only when the logger produces known
spurious V5 keep-alive frames.

For direct RS-485 fallback, set `transport = "serial"`, restore
`serial_port = "/dev/ttyUSB1"`, `baudrate = 9600`, and `parity = "N"`, then pass
the second adapter with `--inverter-serial-device`.

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
- `error`: the logger/network or serial connection, address, or register profile
  did not produce usable telemetry
- `disabled`: inverter collection is disabled

The last good inverter reading is preserved during a later error and is paired
with `last_success_at` and `last_error`. An inverter error does not stop battery
polling and does not make `/healthz` fail; inspect `inverter_status` there.

Prometheus metrics use the `inverter_` prefix, including PV, grid import/export,
load, home load, battery power/SOC, temperatures, per-MPPT values, poll success,
and optional range errors.

The x86 monitor forwards the inverter object inside its live snapshot and uses
its PV, grid, load, state, alarm, fault, and thermal measurements. All
battery-facing dashboard values and battery power history come from the direct
Eco-worthy battery telemetry instead. Inverter-reported battery fields remain
available in the collector response for diagnostics and register validation,
but the monitor does not use them as a fallback.

## First-run validation

Compare all of the following with the LCD while values are changing:

1. PV1-PV4 voltage and total PV power.
2. Grid L1/L2 voltage and import/export direction.
3. Backup load and home-load power, noting which circuits the inverter meters.
4. Battery voltage, SOC, and charge/discharge direction.
5. Inverter and DC-DC temperatures.

If the values are absent in SOLARMAN V5 mode, verify the logger IP, TCP port
8899, printed logger serial, and inverter slave address before assuming a
register problem. For direct RS-485, verify A/B polarity, port pinout, address,
and baud rate. The optional `renogy-x-probe` command remains available for
read-only serial diagnosis; do not write settings while identifying an unknown
firmware variant.
