"""Read-only probe for a battery that answers the Pylontech RS485 protocol.

The first-generation Eco-worthy 51.2 V 314 Ah floor-standing unit carries a
PACE BMS whose RS485 port is set to the Pylontech protocol, so the collector's
JBD-style driver cannot read it. This tool finds the unit on its own adapter
and prints the raw frames it answers with, so the driver can be written
against the unit's real bytes rather than against documentation alone.

It only ever sends read requests (analog values, alarm status, protocol
version, manufacturer info, charge and discharge limits, serial number and
system parameters). There is no write path: nothing here can change a
setting, switch a MOSFET or shut the pack down.

The script has no dependency on the rest of the package so it can be copied
to the Pi and run on its own:

    python3 pylontech_probe.py --port /dev/serial/by-id/usb-...-port0

Frames are ASCII. Request: ~ VER ADR CID1 CID2 LENGTH INFO CHKSUM \\r, where
VER is the protocol version (0x20 for Pylontech, 0x25 for PACE), ADR the pack
address from its DIP switch, CID1 0x46 for a battery, CID2 the command,
LENGTH a 4-bit checksum over a 12-bit INFO length, and CHKSUM the two's
complement of the ASCII sum of everything between ~ and itself. A reply has the
same shape with a return code where the command was.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass

SOI = b"~"
EOI = b"\r"
CID1_BATTERY = 0x46
DEFAULT_VERSIONS = (0x20, 0x25)
DEFAULT_ADDRESSES = "0-15"

# Read-only commands only. (name, CID2, whether INFO carries the pack address)
COMMANDS = (
    ("analog_values", 0x42, True),
    ("alarm_info", 0x44, True),
    ("protocol_version", 0x4F, False),
    ("manufacturer_info", 0x51, False),
    ("charge_discharge_management", 0x92, True),
    ("serial_number", 0x93, True),
    ("system_parameters", 0x47, False),
)

RETURN_CODES = {
    0x00: "ok",
    0x01: "version error",
    0x02: "checksum error",
    0x03: "length checksum error",
    0x04: "invalid command",
    0x05: "command format error",
    0x06: "invalid data",
    0x90: "address error",
    0x91: "communication error",
}


class FrameError(ValueError):
    """A frame that does not follow the protocol's shape."""


def length_field(info_hex: str) -> str:
    """LENGTH: a 4-bit checksum over the three nibbles of the 12-bit INFO length."""
    length = len(info_hex)
    if length > 0xFFF:
        raise ValueError("INFO is too long for a 12-bit length")
    nibble_sum = (length & 0xF) + ((length >> 4) & 0xF) + ((length >> 8) & 0xF)
    check = (~nibble_sum + 1) & 0xF
    return f"{check:X}{length:03X}"


def checksum(body: str) -> str:
    """CHKSUM: two's complement of the ASCII sum of everything between ~ and itself."""
    total = sum(body.encode("ascii"))
    return f"{(~total + 1) & 0xFFFF:04X}"


def build_frame(version: int, address: int, cid2: int, info_hex: str = "") -> bytes:
    """A request frame; the same shape serves a reply when cid2 is its return code."""
    for name, value in (("version", version), ("address", address), ("cid2", cid2)):
        if not 0 <= value <= 0xFF:
            raise ValueError(f"{name} must fit in one byte")
    info_hex = info_hex.upper()
    if len(info_hex) % 2 or any(char not in "0123456789ABCDEF" for char in info_hex):
        raise ValueError("INFO must be an even number of hex characters")
    body = f"{version:02X}{address:02X}{CID1_BATTERY:02X}{cid2:02X}{length_field(info_hex)}{info_hex}"
    return SOI + body.encode("ascii") + checksum(body).encode("ascii") + EOI


def build_request(version: int, address: int, cid2: int, carries_address: bool) -> bytes:
    return build_frame(version, address, cid2, f"{address:02X}" if carries_address else "")


@dataclass(frozen=True)
class Frame:
    version: int
    address: int
    cid1: int
    code: int
    info_hex: str
    checksum_ok: bool
    length_ok: bool

    @property
    def return_code(self) -> str:
        return RETURN_CODES.get(self.code, f"unknown 0x{self.code:02X}")


def parse_frame(raw: bytes) -> Frame:
    """Split a reply into its fields, checking both checksums but keeping the data."""
    if not raw.startswith(SOI) or not raw.endswith(EOI):
        raise FrameError("frame must start with ~ and end with CR")
    try:
        text = raw[1:-1].decode("ascii")
    except UnicodeDecodeError as exc:
        raise FrameError("frame is not ASCII") from exc
    if len(text) < 16:
        raise FrameError("frame is too short for its header")
    body, received = text[:-4], text[-4:]
    try:
        version = int(body[0:2], 16)
        address = int(body[2:4], 16)
        cid1 = int(body[4:6], 16)
        code = int(body[6:8], 16)
        length = int(body[8:12], 16)
    except ValueError as exc:
        raise FrameError("frame header is not hex") from exc
    info_hex = body[12:]
    declared = length & 0xFFF
    return Frame(
        version=version,
        address=address,
        cid1=cid1,
        code=code,
        info_hex=info_hex,
        checksum_ok=checksum(body) == received.upper(),
        length_ok=declared == len(info_hex) and length_field(info_hex) == body[8:12].upper(),
    )


def printable(info_hex: str) -> str:
    """The INFO bytes as text where they are text, for manufacturer and serial replies."""
    try:
        data = bytes.fromhex(info_hex)
    except ValueError:
        return ""
    text = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in data)
    return text if sum(char != "." for char in text) >= 4 else ""


def parse_addresses(spec: str) -> list[int]:
    addresses: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            low, high = (int(value, 0) for value in part.split("-", 1))
            addresses.extend(range(low, high + 1))
        else:
            addresses.append(int(part, 0))
    for address in addresses:
        if not 0 <= address <= 0xFF:
            raise ValueError(f"address {address} does not fit in one byte")
    return addresses


def parse_versions(spec: str) -> list[int]:
    versions = [int(value.strip(), 16) for value in spec.split(",") if value.strip()]
    for version in versions:
        if not 0 <= version <= 0xFF:
            raise ValueError(f"version {version:#x} does not fit in one byte")
    return versions


class SerialLink:
    """One open serial port; replies are read up to the CR that ends every frame."""

    def __init__(self, port: str, baudrate: int, timeout: float) -> None:
        try:
            import serial
        except ImportError as exc:
            raise SystemExit(
                "pyserial is required: pip install pyserial (or apt install python3-serial)"
            ) from exc
        self._connection = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=timeout,
            write_timeout=timeout,
        )

    def transact(self, request: bytes) -> bytes:
        self._connection.reset_input_buffer()
        self._connection.write(request)
        self._connection.flush()
        reply = self._connection.read_until(EOI)
        # Some firmware leads with stray bytes; keep from the frame start.
        start = reply.find(SOI)
        return reply[start:] if start > 0 else reply

    def close(self) -> None:
        self._connection.close()


def describe(raw: bytes) -> dict:
    record: dict = {"raw": raw.decode("ascii", errors="replace")}
    try:
        frame = parse_frame(raw)
    except FrameError as exc:
        record["error"] = str(exc)
        return record
    record.update(asdict(frame))
    record["return"] = frame.return_code
    record["info_bytes"] = len(frame.info_hex) // 2
    text = printable(frame.info_hex)
    if text:
        record["info_text"] = text
    return record


def probe(link: SerialLink, versions: list[int], addresses: list[int], pause: float, verbose: bool) -> list[dict]:
    """Find every (version, address) that answers, then run the read commands on it."""
    found: list[dict] = []
    for address in addresses:
        for version in versions:
            request = build_request(version, address, 0x42, True)
            reply = link.transact(request)
            time.sleep(pause)
            if not reply:
                if verbose:
                    print(f"address {address:#04x} version {version:#04x}: no reply", file=sys.stderr)
                continue
            print(f"address {address:#04x} version {version:#04x}: answered {len(reply)} bytes")
            results = {"address": address, "version": version, "replies": {}}
            results["replies"]["analog_values"] = {"request": request.decode("ascii"), **describe(reply)}
            for name, cid2, carries_address in COMMANDS:
                if name == "analog_values":
                    continue
                request = build_request(version, address, cid2, carries_address)
                reply = link.transact(request)
                time.sleep(pause)
                results["replies"][name] = {
                    "request": request.decode("ascii"),
                    **(describe(reply) if reply else {"raw": "", "error": "no reply"}),
                }
            found.append(results)
    return found


def report(found: list[dict]) -> None:
    for pack in found:
        print(f"\n== pack at address {pack['address']:#04x}, protocol version {pack['version']:#04x} ==")
        for name, result in pack["replies"].items():
            print(f"\n[{name}]")
            print(f"  request  {result['request'].rstrip()}")
            if result.get("error"):
                print(f"  reply    {result['raw'].rstrip() or '(none)'}")
                print(f"  problem  {result['error']}")
                continue
            print(f"  reply    {result['raw'].rstrip()}")
            print(
                f"  return   {result['return']} · {result['info_bytes']} INFO bytes · "
                f"checksum {'ok' if result['checksum_ok'] else 'BAD'} · "
                f"length {'ok' if result['length_ok'] else 'BAD'}"
            )
            if result.get("info_text"):
                print(f"  text     {result['info_text']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only probe for a Pylontech/PACE RS485 battery; prints the raw frames it answers with.",
    )
    parser.add_argument("--port", required=True, help="serial device, e.g. /dev/serial/by-id/usb-...-port0")
    parser.add_argument("--baudrate", type=int, choices=(9600, 19200, 115200), default=9600)
    parser.add_argument("--addresses", default=DEFAULT_ADDRESSES, help="addresses to try, e.g. 0-15 or 1,2,4 (default 0-15)")
    parser.add_argument("--versions", default="20,25", help="protocol version bytes to try, hex (default 20,25)")
    parser.add_argument("--timeout", type=float, default=1.0, help="seconds to wait for each reply")
    parser.add_argument("--pause", type=float, default=0.2, help="seconds between requests")
    parser.add_argument("--json", action="store_true", help="print the results as JSON instead of a report")
    parser.add_argument("--verbose", action="store_true", help="also list the addresses that stay silent")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        addresses = parse_addresses(args.addresses)
        versions = parse_versions(args.versions)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    link = SerialLink(args.port, args.baudrate, args.timeout)
    try:
        print(
            f"probing {args.port} at {args.baudrate} bps, addresses {args.addresses}, "
            f"versions {', '.join(f'{version:#04x}' for version in versions)} (read-only)"
        )
        found = probe(link, versions, addresses, args.pause, args.verbose)
    finally:
        link.close()
    if args.json:
        print(json.dumps(found, indent=2))
    elif found:
        report(found)
    else:
        print(
            "no pack answered. Check A/B wiring (swap them if unsure), the adapter path, "
            "that the pack's RS485 port is the one wired (not a link port), and try "
            "--baudrate 115200 for a console-style port."
        )
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
