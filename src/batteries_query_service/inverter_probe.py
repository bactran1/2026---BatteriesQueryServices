from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Sequence

from .renogy_x import (
    UNDEFINED_REGISTER,
    RenogyXModbusClient,
    RenogyXSerialSettings,
    capture_modbus_frames,
    describe_modbus_frame,
    utc_now,
)


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
