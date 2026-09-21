"""Find a setting's holding register by watching what an LCD change moves.

The inverter's work mode (SELFCONSUME / PEAK SHIFT / BAT PRIORITY) is set from
the front panel, and Megarevo's protocol document does not ship with this
repository, so the register that holds it is unknown. It can still be found
without writing anything: snapshot the configuration registers, change the mode
on the LCD, snapshot again, and see what moved.

The obvious version of that -- one read before, one read after -- does not work
on a live inverter. Power, voltage, temperature and the energy counters all
move between any two reads, so a single diff returns dozens of registers and
buries the one that matters. So each snapshot samples the same range several
times a few seconds apart and sorts registers into two groups:

* **stable** -- held one value across every sample, so it is a candidate for
  holding a setting;
* **volatile** -- moved on its own while nothing was being changed, so it is
  telemetry and can never be the answer.

A register is only a candidate when it was stable before the change, stable
after it, and holds a different value. Everything here reads; nothing in this
module can write, and the caller supplies an already-read mapping.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

# Megarevo leaves unmapped addresses reading as 0xFFFF; they carry no setting.
UNDEFINED_REGISTER = 0xFFFF


def classify_samples(
    samples: Sequence[Mapping[int, int]],
) -> dict[str, Any]:
    """Split repeated reads of one range into stable and volatile registers.

    ``samples`` is the same address range read several times in a row. A
    register counts as stable only when every sample agreed on its value and
    every sample actually returned it: one dropped read makes it unusable as
    evidence, so it is reported as incomplete rather than silently treated as
    stable.
    """
    if not samples:
        raise ValueError("at least one sample is required")

    seen: set[int] = set()
    for sample in samples:
        seen.update(sample)

    stable: dict[int, int] = {}
    volatile: list[int] = []
    incomplete: list[int] = []
    for address in sorted(seen):
        values = [
            sample[address] for sample in samples if address in sample
        ]
        if len(values) != len(samples):
            incomplete.append(address)
            continue
        if any(value == UNDEFINED_REGISTER for value in values):
            continue
        if len(set(values)) == 1:
            stable[address] = values[0]
        else:
            volatile.append(address)

    return {
        "samples": len(samples),
        "stable": stable,
        "volatile": volatile,
        "incomplete": incomplete,
    }


def compare_snapshots(
    baseline: Mapping[str, Any], current: Mapping[str, Any]
) -> dict[str, Any]:
    """Report the registers a change moved, and only those.

    A candidate has to clear every one of these, which is what keeps the live
    inverter's own activity out of the result:

    * stable across the baseline samples;
    * stable across the samples taken after the change;
    * present in both, so a dropped read is never mistaken for a change;
    * holding a different value.
    """
    before = _stable_of(baseline)
    after = _stable_of(current)
    moved_but_unstable = sorted(
        set(_volatile_of(baseline)) | set(_volatile_of(current))
    )

    candidates = []
    for address in sorted(set(before) & set(after)):
        if before[address] == after[address]:
            continue
        candidates.append(
            {
                "register": address,
                "before": register_views(before[address]),
                "after": register_views(after[address]),
            }
        )

    # A register only one side could read is evidence of nothing, but saying so
    # is better than dropping it silently: it usually means the range needs a
    # steadier link or a smaller chunk size.
    unreadable = sorted((set(before) ^ set(after)))

    return {
        "baseline_label": baseline.get("label"),
        "current_label": current.get("label"),
        "baseline_captured_at": baseline.get("captured_at"),
        "current_captured_at": current.get("captured_at"),
        "candidates": candidates,
        "compared_registers": len(set(before) & set(after)),
        "ignored_volatile": moved_but_unstable,
        "unreadable_on_one_side": unreadable,
        "notes": _notes(candidates, before, after, moved_but_unstable),
    }


def _notes(
    candidates: Sequence[Mapping[str, Any]],
    before: Mapping[int, int],
    after: Mapping[int, int],
    volatile: Sequence[int],
) -> list[str]:
    notes: list[str] = []
    if not before or not after:
        notes.append(
            "One side has no stable registers at all; check the range, the "
            "Modbus address, and that the link held for every sample."
        )
        return notes
    if not candidates:
        notes.append(
            "No stable register changed. The setting may live outside the "
            "scanned range, or the mode may not have actually changed."
        )
    elif len(candidates) == 1:
        only = candidates[0]
        notes.append(
            f"Register {only['register']} is the single candidate: "
            f"{only['before']['hex']} -> {only['after']['hex']}."
        )
    else:
        notes.append(
            f"{len(candidates)} registers changed. Repeat the run switching "
            "back to the original mode: the work-mode register is the one that "
            "returns to its first value, and anything that keeps drifting is "
            "not it."
        )
    if volatile:
        notes.append(
            f"{len(volatile)} register(s) moved on their own and were excluded "
            "as telemetry."
        )
    notes.append(
        "Confirm a candidate by reading it back after another LCD change. "
        "Nothing here writes to the inverter."
    )
    return notes


def register_views(value: int) -> dict[str, Any]:
    """The same raw register shown the handful of ways a setting might mean."""
    signed = value - 0x10000 if value & 0x8000 else value
    return {
        "hex": f"0x{value:04X}",
        "unsigned": value,
        "signed": signed,
        "tenths": round(signed / 10, 1),
        "hundredths": round(signed / 100, 2),
    }


def _stable_of(snapshot: Mapping[str, Any]) -> dict[int, int]:
    stable = snapshot.get("stable") or {}
    return {int(address): int(value) for address, value in stable.items()}


def _volatile_of(snapshot: Mapping[str, Any]) -> list[int]:
    return [int(address) for address in (snapshot.get("volatile") or [])]


def parse_ranges(values: Iterable[str] | None, default: Sequence[str]) -> list[tuple[int, int]]:
    """Parse ``START:END`` range arguments into ``(start, count)`` pairs."""
    ranges: list[tuple[int, int]] = []
    for value in list(values or default):
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
