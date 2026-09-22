from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Sequence

from .register_discovery import (
    READ_REFUSED,
    classify_samples,
    compare_snapshots,
    format_range,
    format_ranges_of,
    map_readable_blocks,
    read_blocks_resiliently,
)
from .register_discovery import parse_ranges as parse_discovery_ranges
from .renogy_x import (
    UNDEFINED_REGISTER,
    RenogyXModbusClient,
    RenogyXSerialSettings,
    capture_modbus_frames,
    describe_modbus_frame,
    utc_now,
)
from .solarman_v5 import SolarmanV5ModbusClient, SolarmanV5Settings

# Where a Megarevo-family inverter's settings plausibly live. The telemetry this
# service reads sits at 0x3100+; the protocol version and serial number answer
# from 0x1219 and 0x1234, so the surrounding blocks are the first place to look
# for the work-mode register. Widen with --range if nothing turns up.
DISCOVERY_RANGES = ("0x1000:0x13FF", "0x2000:0x20FF")

# What `map` sweeps by default. The first two are where a setting plausibly
# lives; 0x3100:0x31FF holds the telemetry this service reads every poll,
# included as a positive control: 0x3100 through 0x31AD must come back readable,
# or the map is not to be trusted. (The driver skips a few addresses inside that
# span, but that is the driver's choice -- a live map showed the inverter
# answers the whole block, and on past 0x31FF.)
MAP_RANGES = ("0x1000:0x13FF", "0x2000:0x20FF", "0x3100:0x31FF")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            return capture(args)
        require_active_acknowledgement(args)
        if args.command == "profile":
            return profile(args)
        if args.command == "dump":
            return dump(args)
        if args.command == "watch":
            return watch(args)
        if args.command == "snapshot":
            return snapshot(args)
        if args.command == "compare":
            return compare(args)
        if args.command == "map":
            return map_blocks(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parser.error("a command is required")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="renogy-x-probe",
        description=(
            "Read-only Modbus RTU discovery tool for the Renogy X hybrid inverter"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    profile_parser = subparsers.add_parser(
        "profile",
        help="test Renogy's public common inverter register profile",
    )
    add_serial_arguments(profile_parser)
    add_active_argument(profile_parser)
    profile_parser.add_argument("--json", action="store_true")

    dump_parser = subparsers.add_parser(
        "dump", help="dump one or more holding-register ranges"
    )
    add_serial_arguments(dump_parser)
    add_active_argument(dump_parser)
    add_range_arguments(dump_parser)
    dump_parser.add_argument("--include-ffff", action="store_true")
    dump_parser.add_argument("--json", action="store_true")

    watch_parser = subparsers.add_parser(
        "watch", help="show registers that change while the inverter operates"
    )
    add_serial_arguments(watch_parser)
    add_active_argument(watch_parser)
    add_range_arguments(watch_parser)
    watch_parser.add_argument("--interval", type=float, default=2.0)
    watch_parser.add_argument("--duration", type=float, default=60.0)
    watch_parser.add_argument("--json", action="store_true")

    snapshot_parser = subparsers.add_parser(
        "snapshot",
        help=(
            "sample settings registers repeatedly and record which ones hold "
            "still (read-only; run once per work mode)"
        ),
    )
    add_transport_arguments(snapshot_parser)
    add_active_argument(snapshot_parser)
    add_discovery_range_arguments(snapshot_parser)
    snapshot_parser.add_argument(
        "--label",
        required=True,
        help="what the inverter is set to right now, e.g. SELFCONSUME",
    )
    snapshot_parser.add_argument(
        "--out", required=True, help="file to write the snapshot to"
    )
    snapshot_parser.add_argument("--samples", type=int, default=4)
    snapshot_parser.add_argument("--interval", type=float, default=3.0)

    compare_parser = subparsers.add_parser(
        "compare",
        help=(
            "take a second snapshot and report which stable register the mode "
            "change moved (read-only)"
        ),
    )
    add_transport_arguments(compare_parser)
    add_active_argument(compare_parser)
    add_discovery_range_arguments(compare_parser)
    compare_parser.add_argument(
        "--baseline", required=True, help="snapshot file taken before the change"
    )
    compare_parser.add_argument(
        "--label",
        required=True,
        help="what the inverter is set to now, e.g. BAT PRIORITY",
    )
    compare_parser.add_argument("--out", help="optional file to write this snapshot to")
    compare_parser.add_argument("--samples", type=int, default=4)
    compare_parser.add_argument("--interval", type=float, default=3.0)
    compare_parser.add_argument("--json", action="store_true")

    map_parser = subparsers.add_parser(
        "map",
        help=(
            "find which register blocks the inverter answers at all, by "
            "halving refused reads (read-only)"
        ),
    )
    add_transport_arguments(map_parser)
    add_active_argument(map_parser)
    add_discovery_range_arguments(map_parser, MAP_RANGES)
    map_parser.add_argument(
        "--stride",
        type=int,
        default=8,
        help=(
            "probe one register every STRIDE addresses; every block at least "
            "this wide is found, narrower ones can slip between probes "
            "(default: 8)"
        ),
    )
    map_parser.add_argument(
        "--max-reads",
        type=int,
        default=2000,
        help="bound on the sweep; what is left over is reported (default: 2000)",
    )
    map_parser.add_argument("--out", help="file to write the map to")
    map_parser.add_argument("--json", action="store_true")

    capture_parser = subparsers.add_parser(
        "capture",
        help="passively capture Modbus frames without transmitting",
    )
    add_serial_arguments(capture_parser)
    capture_parser.add_argument("--duration", type=float, default=30.0)
    capture_parser.add_argument("--silence-ms", type=float)
    capture_parser.add_argument("--json", action="store_true")

    return parser


def add_serial_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", required=True, help="serial device, e.g. /dev/ttyUSB1")
    parser.add_argument("--baudrate", type=int, choices=(9600, 19200), default=9600)
    parser.add_argument("--parity", choices=("N", "E", "O"), default="N")
    parser.add_argument("--address", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=2.0)


def add_active_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--active",
        action="store_true",
        help="confirm this tool may transmit read-only Modbus requests",
    )


def add_transport_arguments(parser: argparse.ArgumentParser) -> None:
    """Serial or the SOLARMAN logger.

    Discovery has to work over whichever link the inverter is actually on. This
    deployment reads it through the LSW-5 logger, so serial-only would make the
    tool useless here.
    """
    parser.add_argument(
        "--transport",
        choices=("serial", "solarman"),
        default="serial",
        help="how to reach the inverter (default: serial)",
    )
    parser.add_argument("--port", help="serial device, e.g. /dev/ttyUSB1")
    parser.add_argument("--baudrate", type=int, choices=(9600, 19200), default=9600)
    parser.add_argument("--parity", choices=("N", "E", "O"), default="N")
    parser.add_argument("--host", help="SOLARMAN logger address")
    parser.add_argument("--logger-serial", type=int, help="serial printed on the logger")
    parser.add_argument("--logger-port", type=int, default=8899)
    parser.add_argument("--address", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=2.0)


def add_discovery_range_arguments(
    parser: argparse.ArgumentParser,
    default_ranges: Sequence[str] = DISCOVERY_RANGES,
) -> None:
    parser.add_argument(
        "--range",
        action="append",
        dest="ranges",
        metavar="START:END",
        help=(
            "inclusive register range; may be repeated (default: "
            + ", ".join(default_ranges)
            + ")"
        ),
    )
    parser.add_argument(
        "--ranges-from",
        metavar="MAP",
        help=(
            "read the ranges from a 'map' result instead, so a snapshot asks "
            "only for blocks the inverter answers"
        ),
    )
    parser.add_argument("--chunk-size", type=int, default=60)


def resolve_ranges(
    args: argparse.Namespace, default_ranges: Sequence[str]
) -> list[tuple[int, int]]:
    """Explicit --range wins, then a map file, then the built-in default."""
    if args.ranges:
        return parse_discovery_ranges(args.ranges, default_ranges)
    source = getattr(args, "ranges_from", None)
    if source:
        with open(source, encoding="utf-8") as handle:
            mapped = json.load(handle).get("ranges") or []
        if not mapped:
            raise ValueError(f"{source} lists no readable ranges")
        return parse_discovery_ranges(mapped, default_ranges)
    return parse_discovery_ranges(None, default_ranges)


def discovery_client(args: argparse.Namespace):
    if args.transport == "solarman":
        if not args.host or args.logger_serial is None:
            raise ValueError(
                "--host and --logger-serial are required for --transport solarman"
            )
        return SolarmanV5ModbusClient(
            SolarmanV5Settings(
                host=args.host,
                logger_serial=args.logger_serial,
                port=args.logger_port,
                timeout_seconds=args.timeout,
            )
        )
    if not args.port:
        raise ValueError("--port is required for --transport serial")
    return RenogyXModbusClient(
        RenogyXSerialSettings(
            port=args.port,
            baudrate=args.baudrate,
            timeout_seconds=args.timeout,
            parity=args.parity,
        )
    )


def collect_snapshot(args: argparse.Namespace, label: str) -> dict:
    """Read the ranges several times so telemetry can be told from settings."""
    if args.samples < 2:
        raise ValueError("at least two samples are needed to spot a moving register")
    if args.interval <= 0:
        raise ValueError("sample interval must be greater than zero")

    ranges = resolve_ranges(args, DISCOVERY_RANGES)
    client = discovery_client(args)
    wanted = sum(count for _, count in ranges)

    def read(start: int, count: int) -> list[int]:
        return client.read_holding_registers(args.address, start, count)

    samples: list[dict[int, int]] = []
    errors: list[dict[str, object]] = []
    for index in range(args.samples):
        if index:
            time.sleep(args.interval)
        # A chunk lost to one dropped frame would drop every register in it
        # from the whole comparison, so reads here retry and split rather
        # than give up on sixty registers at once.
        registers, read_errors = read_blocks_resiliently(
            read, ranges, chunk_size=args.chunk_size, sleep=time.sleep
        )
        samples.append(registers)
        errors.extend(read_errors)
        missing = wanted - len(registers)
        detail = f", {missing} not read" if missing else ""
        print(
            f"sample {index + 1}/{args.samples}: {len(registers)} registers{detail}",
            file=sys.stderr,
        )

    classified = classify_samples(samples)
    return {
        "captured_at": utc_now(),
        "label": label,
        "transport": args.transport,
        "address": args.address,
        "ranges": [[start, count] for start, count in ranges],
        "interval_seconds": args.interval,
        "read_errors": errors,
        **classified,
    }


def snapshot(args: argparse.Namespace) -> int:
    result = collect_snapshot(args, args.label)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
    print(
        f"{args.label}: {len(result['stable'])} stable, "
        f"{len(result['volatile'])} moving on their own -> {args.out}"
    )
    _report_unread(result)
    print(
        "Now change the work mode on the inverter's LCD "
        "(SYS SETTING > SETUP > WORK MODE), then run 'compare'."
    )
    return 0


def _report_unread(snapshot: dict) -> None:
    """Name what a snapshot could not read, so the next run can be exact."""
    errors = snapshot.get("read_errors") or []
    refused = {
        address
        for error in errors
        if error.get("kind") == READ_REFUSED
        for address in range(int(error["start"]), int(error["start"]) + int(error["count"]))
    }
    dropped = {
        address
        for error in errors
        if error.get("kind") != READ_REFUSED
        for address in range(int(error["start"]), int(error["start"]) + int(error["count"]))
    }
    if refused:
        print(
            f"  refused as out of range ({len(refused)} register(s)): "
            + ", ".join(format_ranges_of(refused)),
            file=sys.stderr,
        )
        print("    remap those with 'map' before trusting a result there.", file=sys.stderr)
    if dropped:
        print(
            f"  lost on the link after retries ({len(dropped)} register(s)): "
            + ", ".join(format_ranges_of(dropped)),
            file=sys.stderr,
        )
    incomplete = snapshot.get("incomplete") or []
    if incomplete:
        print(
            f"  {len(incomplete)} register(s) missed at least one sample and "
            "cannot be compared: " + ", ".join(format_ranges_of(incomplete)),
            file=sys.stderr,
        )


def compare(args: argparse.Namespace) -> int:
    with open(args.baseline, encoding="utf-8") as handle:
        baseline = json.load(handle)
    current = collect_snapshot(args, args.label)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(current, handle, indent=2, sort_keys=True)

    result = compare_snapshots(baseline, current)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    print()
    print(
        f"{result['baseline_label']} -> {result['current_label']}: "
        f"{len(result['candidates'])} candidate register(s) "
        f"out of {result['compared_registers']} compared"
    )
    for candidate in result["candidates"]:
        before, after = candidate["before"], candidate["after"]
        print(
            f"  register 0x{candidate['register']:04X} "
            f"({candidate['register']})  "
            f"{before['hex']} -> {after['hex']}  "
            f"({before['unsigned']} -> {after['unsigned']})"
        )
    for note in result["notes"]:
        print(f"  - {note}")
    if result["unreadable_on_one_side"]:
        # Say where, not just how many: whether the settings block was in the
        # comparison at all is the first thing to check when nothing turns up.
        print(
            f"  - {len(result['unreadable_on_one_side'])} register(s) were "
            "readable on only one side and were not compared: "
            + ", ".join(format_ranges_of(result["unreadable_on_one_side"])),
            file=sys.stderr,
        )
    _report_unread(current)
    return 0


def map_blocks(args: argparse.Namespace) -> int:
    """Sweep for readable blocks so a snapshot can ask only for those."""
    ranges = resolve_ranges(args, MAP_RANGES)
    client = discovery_client(args)
    scanned = sum(count for _, count in ranges)
    print(
        f"mapping {scanned} register(s) across {len(ranges)} range(s), "
        f"probing every {args.stride}",
        file=sys.stderr,
    )

    def read(start: int, count: int) -> list[int]:
        return client.read_holding_registers(args.address, start, count)

    reads_so_far = 0

    def progress(start: int, count: int, outcome: str) -> None:
        # A long refused stretch is silent otherwise, and over the logger a
        # wide sweep runs for minutes; say something now and then so it does
        # not look hung.
        nonlocal reads_so_far
        reads_so_far += 1
        if outcome == "ok":
            print(f"  {format_range(start, count)} answered", file=sys.stderr)
        elif reads_so_far % 100 == 0:
            print(f"  ... {reads_so_far} reads, at 0x{start:04X}", file=sys.stderr)

    result = map_readable_blocks(
        read,
        ranges,
        stride=args.stride,
        edge_read=args.chunk_size,
        max_reads=args.max_reads,
        on_read=progress,
    )
    result["captured_at"] = utc_now()
    result["address"] = args.address
    result["transport"] = args.transport
    result["scanned_ranges"] = [format_range(start, count) for start, count in ranges]

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(_jsonable_map(result), handle, indent=2, sort_keys=True)
    if args.json:
        print(json.dumps(_jsonable_map(result), indent=2, sort_keys=True))
        return 0

    readable = result["readable"]
    total = sum(count for _, count in readable)
    print()
    print(
        f"{len(readable)} readable block(s), {total} register(s), "
        f"in {result['reads']} read(s)"
    )
    edges = {start for start, _ in ranges} | {start + count - 1 for start, count in ranges}
    for start, count in readable:
        undefined = sum(
            1
            for address in range(start, start + count)
            if result["values"].get(address) == UNDEFINED_REGISTER
        )
        suffix = f", {undefined} reading 0xFFFF" if undefined else ""
        # The walk stops at the edge of the range it was given, so a block that
        # ends exactly there has not been shown to end at all.
        if start in edges or start + count - 1 in edges:
            suffix += ", reaches the edge of the sweep and may continue"
        print(f"  {format_range(start, count)}  {count} register(s){suffix}")
    if not readable:
        print(
            f"  none; nothing at least {result['stride']} register(s) wide "
            "answered. Lower --stride or widen --range."
        )
    if result["unverified"]:
        print(
            f"  {len(result['unverified'])} span(s) failed on the link rather "
            "than being refused, so they are neither in the map nor proven "
            "absent. Rerun them with:"
        )
        print(
            "    map "
            + " ".join(
                f"--range {format_range(start, count)}"
                for start, count in result["unverified"]
            )
        )
    if result["budget_exhausted"]:
        print(
            f"  budget spent with {len(result['unscanned'])} block(s) unscanned; "
            "raise --max-reads or narrow --range"
        )
    if args.out:
        print()
        print(f"map written to {args.out}")
        print(f"  reuse it with: snapshot --ranges-from {args.out}")
    return 0


def _jsonable_map(result: dict) -> dict:
    """Tuples and integer keys do not survive JSON; ranges have to come back."""
    blocks = ("readable", "refused", "unverified", "unscanned")
    return {
        **{key: value for key, value in result.items() if key not in blocks},
        **{
            key: [format_range(start, count) for start, count in result[key]]
            for key in blocks
        },
        "values": {str(address): value for address, value in result["values"].items()},
    }


def add_range_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--range",
        action="append",
        dest="ranges",
        metavar="START:END",
        help=(
            "inclusive decimal register range; may be repeated "
            "(default: 4000:4059, 4100:4199, 4300:4615)"
        ),
    )
    parser.add_argument("--chunk-size", type=int, default=60)


def serial_settings(args: argparse.Namespace) -> RenogyXSerialSettings:
    return RenogyXSerialSettings(
        port=args.port,
        baudrate=args.baudrate,
        timeout_seconds=args.timeout,
        parity=args.parity,
    )


def require_active_acknowledgement(args: argparse.Namespace) -> None:
    if not args.active:
        raise ValueError(
            "active reads are disabled until --active is supplied; make sure this "
            "port has no other Modbus master"
        )


def profile(args: argparse.Namespace) -> int:
    result = RenogyXModbusClient(serial_settings(args)).read_common_profile(args.address)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    print(
        f"Renogy common profile on {args.port} at {args.baudrate} bps "
        f"(address {args.address})"
    )
    for name, field in result["fields"].items():
        if field is None:
            print(f"  {name:<28} unavailable")
            continue
        unit = field.get("unit") or ""
        print(
            f"  {name:<28} {field['value']} {unit:<3} "
            f"(register {field['address']}, raw {field['raw']})"
        )
    assessment = result["assessment"]
    print(f"Assessment: {assessment['status']}")
    for note in assessment["notes"]:
        print(f"  - {note}")
    for error in result["read_errors"]:
        print(
            f"  - read {error['start']}+{error['count']} failed: {error['error']}",
            file=sys.stderr,
        )
    return 0


def dump(args: argparse.Namespace) -> int:
    ranges = parse_ranges(args.ranges)
    registers, errors = RenogyXModbusClient(serial_settings(args)).read_ranges(
        args.address,
        ranges,
        chunk_size=args.chunk_size,
        continue_on_error=True,
    )
    filtered = {
        address: value
        for address, value in registers.items()
        if args.include_ffff or value != UNDEFINED_REGISTER
    }
    if args.json:
        print(
            json.dumps(
                {
                    "captured_at": utc_now(),
                    "address": args.address,
                    "serial_port": args.port,
                    "baudrate": args.baudrate,
                    "registers": {
                        str(address): register_views(value)
                        for address, value in sorted(filtered.items())
                    },
                    "read_errors": errors,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    print("register  hex     unsigned  signed   /10      /100")
    for address, value in sorted(filtered.items()):
        views = register_views(value)
        print(
            f"{address:>8}  0x{value:04X}  {value:>8}  {views['signed']:>6}  "
            f"{views['tenths']:>7.1f}  {views['hundredths']:>7.2f}"
        )
    for error in errors:
        print(
            f"read {error['start']}+{error['count']} failed: {error['error']}",
            file=sys.stderr,
        )
    return 0


def watch(args: argparse.Namespace) -> int:
    if args.interval <= 0 or args.duration <= 0:
        raise ValueError("watch interval and duration must be greater than zero")
    ranges = parse_ranges(args.ranges)
    client = RenogyXModbusClient(serial_settings(args))
    previous: dict[int, int] | None = None
    deadline = time.monotonic() + args.duration

    while time.monotonic() < deadline:
        registers, errors = client.read_ranges(
            args.address,
            ranges,
            chunk_size=args.chunk_size,
            continue_on_error=True,
        )
        current = {
            address: value
            for address, value in registers.items()
            if value != UNDEFINED_REGISTER
        }
        if previous is not None:
            for address in sorted(set(previous) | set(current)):
                before = previous.get(address)
                after = current.get(address)
                if before == after:
                    continue
                event = {
                    "captured_at": utc_now(),
                    "register": address,
                    "before": register_views(before) if before is not None else None,
                    "after": register_views(after) if after is not None else None,
                }
                if args.json:
                    print(json.dumps(event, separators=(",", ":")), flush=True)
                else:
                    print(
                        f"{event['captured_at']} register {address}: "
                        f"{before} -> {after} ({event['after']})",
                        flush=True,
                    )
        for error in errors:
            print(
                f"read {error['start']}+{error['count']} failed: {error['error']}",
                file=sys.stderr,
            )
        previous = current
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(args.interval, remaining))
    return 0


def capture(args: argparse.Namespace) -> int:
    if args.duration <= 0:
        raise ValueError("capture duration must be greater than zero")
    silence = None
    if args.silence_ms is not None:
        if args.silence_ms <= 0:
            raise ValueError("silence interval must be greater than zero")
        silence = args.silence_ms / 1000

    for frame in capture_modbus_frames(
        serial_settings(args),
        duration_seconds=args.duration,
        silence_seconds=silence,
    ):
        description = describe_modbus_frame(frame)
        if args.json:
            print(json.dumps(description, separators=(",", ":")), flush=True)
        else:
            print(
                f"{description['captured_at']} {description['kind']:<18} "
                f"crc={description['crc_valid']} {description['hex']}",
                flush=True,
            )
    return 0


def parse_ranges(values: list[str] | None) -> list[tuple[int, int]]:
    raw_ranges = values or ["4000:4059", "4100:4199", "4300:4615"]
    ranges = []
    for value in raw_ranges:
        try:
            start_text, end_text = value.split(":", maxsplit=1)
            start = int(start_text, 0)
            end = int(end_text, 0)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid register range {value!r}; use START:END") from exc
        if not 0 <= start <= end <= 0xFFFF:
            raise ValueError(f"Invalid register range {value!r}")
        ranges.append((start, end - start + 1))
    return ranges


def register_views(value: int) -> dict[str, int | float | str]:
    signed = value - 0x10000 if value & 0x8000 else value
    return {
        "hex": f"0x{value:04X}",
        "unsigned": value,
        "signed": signed,
        "tenths": round(signed / 10, 1),
        "hundredths": round(signed / 100, 2),
    }


if __name__ == "__main__":
    raise SystemExit(main())
