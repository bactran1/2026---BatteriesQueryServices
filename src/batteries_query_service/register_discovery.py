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
after it, and holds a different value.

That still assumes the inverter will answer for the addresses being watched, and
this one refuses most of its space. :func:`map_readable_blocks` finds the blocks
it does answer for, so a snapshot can ask for those and nothing else; the reason
a fixed-chunk sweep cannot do that job is set out above it.

Everything here reads; nothing in this module can write, and the caller supplies
the reads.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
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
            "scanned range, or the mode may not have actually changed. If the "
            "snapshots were full of refused reads, run 'map' first: a range "
            "that answers only in places reports almost nothing here."
        )
    elif len(candidates) == 1:
        only = candidates[0]
        notes.append(
            f"Register 0x{only['register']:04X} ({only['register']}) is the "
            f"single candidate: {only['before']['hex']} -> "
            f"{only['after']['hex']}."
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


# ---------------------------------------------------------------------------
# Finding which blocks answer at all
# ---------------------------------------------------------------------------
#
# A snapshot can only classify registers the inverter agreed to return, and this
# one answers "illegal data address" for most of the space. Modbus refuses a
# read when *any* address in it is out of range, so a 60-register chunk laid
# over a gap fails whole and hides every readable register beside it. A sweep in
# fixed chunks therefore reports far less than the inverter exposes, which is
# what makes a discovery run come back empty.
#
# A single-register read has no such ambiguity: it answers for exactly one
# address. So the map probes one register every `stride` addresses, which finds
# every block at least `stride` wide, and then walks each hit out to its edges.
# Because a multi-register read succeeds only when the whole span is defined,
# "does this span read?" is monotone in the span, and the edges come out of a
# binary search rather than a register-by-register walk. Every read that lands
# hands back the values it covered, so the map carries them at no extra cost.

READ_OK = "ok"
READ_REFUSED = "refused"
READ_FAILED = "failed"

# Modbus caps one read, and the existing driver reads in 60-register chunks over
# this logger, so edge searches stay inside a width already known to work.
DEFAULT_EDGE_READ = 60

# The two stacks phrase the same Modbus exception 0x02 differently: umodbus
# (under pysolarmanv5) raises IllegalDataAddressError carrying its docstring,
# and the serial driver raises RenogyXProtocolError naming the numeric code.
_REFUSAL_PATTERN = re.compile(
    r"not an allowable address|illegal ?data ?address|modbus exception 0?2\b"
)


def classify_read_failure(error: BaseException) -> str:
    """Tell a refusal from a link problem.

    An inverter that answers "illegal data address" has said something true
    about the address, so the map can act on it. A timeout or a mangled frame
    has said only that the link wavered, and treating that as a gap would carve
    a hole into the map that is not in the inverter -- the next snapshot would
    then skip real registers and never find what it was looking for.
    """
    text = " ".join(f"{type(error).__name__} {error}".lower().split())
    return READ_REFUSED if _REFUSAL_PATTERN.search(text) else READ_FAILED


def map_readable_blocks(
    read: Callable[[int, int], Sequence[int]],
    ranges: Iterable[tuple[int, int]],
    *,
    stride: int = 8,
    max_reads: int = 2000,
    edge_read: int = DEFAULT_EDGE_READ,
    retries: int = 1,
    on_read: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Map the blocks an inverter will answer for, within the given ranges.

    ``read(start, count)`` returns the block's values or raises. Probing one
    register every ``stride`` addresses finds every block at least ``stride``
    wide; a narrower block can fall between two probes and be missed, so
    ``stride`` is the map's resolution and lowering it is what widens the net.

    ``max_reads`` bounds the sweep. Whatever it did not reach is reported as
    unscanned rather than quietly folded in with the refusals.
    """
    if stride < 1:
        raise ValueError("stride must be at least one register")
    if max_reads < 1:
        raise ValueError("at least one read is required")
    if not 1 <= edge_read <= 125:
        raise ValueError("edge read width must be between 1 and 125 registers")

    state = _MapRun(read, max_reads, retries, on_read)
    islands: list[tuple[int, int]] = []
    refused: list[tuple[int, int]] = []
    unverified: list[tuple[int, int]] = []
    unscanned: list[tuple[int, int]] = []
    probes = 0

    for start, count in ranges:
        limit = start + count - 1
        probe = start
        while probe <= limit:
            if state.exhausted:
                unscanned.append((probe, limit - probe + 1))
                break
            covered = _covering(islands, probe)
            if covered is not None:
                # Already inside a block the map walked out; nothing to ask.
                probe = covered + stride
                continue

            probes += 1
            outcome, _ = state.read(probe, 1)
            if outcome == READ_OK:
                low = _edge_down(state, probe, start, edge_read)
                high = _edge_up(state, probe, limit, edge_read)
                islands.append((low, high - low + 1))
                probe = high + stride
                continue
            if outcome == READ_REFUSED:
                refused.append((probe, 1))
            else:
                unverified.append((probe, 1))
            probe += stride

    # Two islands that touch were walked separately, which means a read
    # spanning the join was refused: the inverter treats them as two pages.
    # Joining them would hand the snapshot a range it cannot read in one
    # chunk, and Modbus refuses the whole chunk. Only overlap is joined.
    readable = _merge_blocks(islands, touching=False)
    return {
        "reads": state.reads,
        "probes": probes,
        "stride": stride,
        "budget_exhausted": state.exhausted,
        "readable": readable,
        "refused": _merge_blocks(refused),
        # A doubt another probe later settled is no longer a doubt.
        "unverified": _subtract_blocks(
            _merge_blocks(unverified + state.doubts), readable
        ),
        "unscanned": _merge_blocks(unscanned),
        "ranges": [format_range(start, count) for start, count in readable],
        "values": state.values,
    }


class _MapRun:
    """The read budget, the retry rule, and the values collected along the way."""

    def __init__(self, read, max_reads: int, retries: int, on_read) -> None:
        self._read = read
        self._max_reads = max_reads
        self._retries = max(0, retries)
        self._on_read = on_read
        self.reads = 0
        self.values: dict[int, int] = {}
        self.doubts: list[tuple[int, int]] = []

    @property
    def exhausted(self) -> bool:
        return self.reads >= self._max_reads

    def read(self, start: int, count: int) -> tuple[str, Sequence[int] | None]:
        outcome = READ_FAILED
        attempted = False
        for _ in range(self._retries + 1):
            if self.exhausted:
                break
            attempted = True
            self.reads += 1
            try:
                values = list(self._read(start, count))
            except Exception as exc:  # noqa: BLE001 - every failure is classified
                outcome = classify_read_failure(exc)
                if outcome == READ_REFUSED:
                    break
                continue
            self._report(start, count, READ_OK)
            for index, value in enumerate(values):
                self.values[start + index] = int(value)
            return READ_OK, values
        if attempted:
            self._report(start, count, outcome)
        return outcome, None

    def _report(self, start: int, count: int, outcome: str) -> None:
        if self._on_read is not None:
            self._on_read(start, count, outcome)

    def outcome(self, start: int, count: int) -> str:
        return self.read(start, count)[0]

    def doubt(self, start: int, count: int) -> None:
        """Addresses an edge walk could not settle because the link failed."""
        if count > 0:
            self.doubts.append((start, count))


def _edge_up(state: "_MapRun", known: int, limit: int, edge_read: int) -> int:
    """Walk up from a defined address to the last one still in the same block.

    Only a refusal marks an edge. A read that fails on the link has said
    nothing about the addresses, so the walk stops at the last proven address
    and reports the rest as unverified rather than cutting the block short
    there: a snapshot built on a truncated block would skip real registers.
    """
    end = known
    while end < limit and not state.exhausted:
        width = min(edge_read, limit - end)
        outcome = state.outcome(end + 1, width)
        if outcome == READ_OK:
            end += width
            continue
        if outcome != READ_REFUSED:
            state.doubt(end + 1, width)
            return end
        # Somewhere in the next `width` registers the block stops. A read
        # succeeds only when every address in it is defined, so the largest
        # span that still answers is found by bisection.
        low, high, best = 1, width - 1, 0
        while low <= high and not state.exhausted:
            middle = (low + high) // 2
            outcome = state.outcome(end + 1, middle)
            if outcome == READ_OK:
                best, low = middle, middle + 1
            elif outcome == READ_REFUSED:
                high = middle - 1
            else:
                # Proven good up to end+best, proven refused past end+high;
                # what lies between is what the failed read was asking about.
                state.doubt(end + 1 + best, high - best)
                break
        return end + best
    return end


def _edge_down(state: "_MapRun", known: int, floor: int, edge_read: int) -> int:
    """The same walk downwards, since a probe can land anywhere in a block."""
    start = known
    while start > floor and not state.exhausted:
        width = min(edge_read, start - floor)
        outcome = state.outcome(start - width, width)
        if outcome == READ_OK:
            start -= width
            continue
        if outcome != READ_REFUSED:
            state.doubt(start - width, width)
            return start
        low, high, best = 1, width - 1, 0
        while low <= high and not state.exhausted:
            middle = (low + high) // 2
            outcome = state.outcome(start - middle, middle)
            if outcome == READ_OK:
                best, low = middle, middle + 1
            elif outcome == READ_REFUSED:
                high = middle - 1
            else:
                state.doubt(start - high, high - best)
                break
        return start - best
    return start


def _covering(islands: Sequence[tuple[int, int]], address: int) -> int | None:
    """The last address of the block holding ``address``, when one does."""
    for start, count in islands:
        if start <= address < start + count:
            return start + count - 1
    return None


def _merge_blocks(
    blocks: Iterable[tuple[int, int]], *, touching: bool = True
) -> list[tuple[int, int]]:
    """Join blocks that overlap, and with ``touching`` those that merely abut."""
    merged: list[tuple[int, int]] = []
    for start, count in sorted(blocks):
        previous_end = merged[-1][0] + merged[-1][1] if merged else None
        joins = previous_end is not None and (
            start < previous_end or (touching and start == previous_end)
        )
        if joins:
            previous_start, previous_count = merged[-1]
            end = max(previous_start + previous_count, start + count)
            merged[-1] = (previous_start, end - previous_start)
        else:
            merged.append((start, count))
    return merged


def _subtract_blocks(
    blocks: Iterable[tuple[int, int]], remove: Iterable[tuple[int, int]]
) -> list[tuple[int, int]]:
    """``blocks`` with every address in ``remove`` taken out."""
    result: list[tuple[int, int]] = []
    removals = sorted(remove)
    for start, count in blocks:
        cursor, end = start, start + count
        for gap_start, gap_count in removals:
            gap_end = gap_start + gap_count
            if gap_end <= cursor or gap_start >= end:
                continue
            if gap_start > cursor:
                result.append((cursor, gap_start - cursor))
            cursor = max(cursor, gap_end)
        if cursor < end:
            result.append((cursor, end - cursor))
    return result


def read_blocks_resiliently(
    read: Callable[[int, int], Sequence[int]],
    ranges: Iterable[tuple[int, int]],
    *,
    chunk_size: int = 60,
    retries: int = 2,
    extra_reads: int = 200,
    sleep: Callable[[float], None] | None = None,
    retry_delay: float = 0.15,
    inter_request_delay: float = 0.02,
) -> tuple[dict[int, int], list[dict[str, Any]]]:
    """Read ranges in chunks without letting one bad read take a chunk down.

    A link failure is retried, since it says nothing about the addresses. A
    refusal is split: Modbus refuses a read when any address in it is out of
    range or when it crosses a page the inverter keeps separate, and either
    way the halves usually answer. Splitting is bounded by ``extra_reads`` so a
    stale map that names whole blocks the inverter no longer answers cannot
    turn one snapshot into hundreds of reads; past the bound a refused chunk
    is recorded as refused, whole.
    """
    if not 1 <= chunk_size <= 125:
        raise ValueError("chunk size must be between 1 and 125 registers")
    if retries < 0:
        raise ValueError("retries cannot be negative")

    queue: deque[tuple[int, int]] = deque()
    for start, count in ranges:
        for offset in range(0, count, chunk_size):
            queue.append((start + offset, min(chunk_size, count - offset)))

    values: dict[int, int] = {}
    errors: list[dict[str, Any]] = []
    splits_left = extra_reads
    while queue:
        start, count = queue.popleft()
        outcome, block, attempts, text = _try_read(
            read, start, count, retries, sleep, retry_delay
        )
        if sleep is not None and inter_request_delay:
            sleep(inter_request_delay)
        if outcome == READ_OK and block is not None:
            for index, value in enumerate(block):
                values[start + index] = int(value)
        elif outcome == READ_REFUSED and count > 1 and splits_left > 0:
            splits_left -= 1
            half = count // 2
            queue.appendleft((start + half, count - half))
            queue.appendleft((start, half))
        else:
            errors.append(
                {
                    "start": start,
                    "count": count,
                    "attempts": attempts,
                    "kind": outcome,
                    "error": text,
                }
            )
    return values, errors


def _try_read(
    read: Callable[[int, int], Sequence[int]],
    start: int,
    count: int,
    retries: int,
    sleep: Callable[[float], None] | None,
    retry_delay: float,
) -> tuple[str, Sequence[int] | None, int, str]:
    outcome, text = READ_FAILED, ""
    attempts = 0
    while attempts <= retries:
        attempts += 1
        try:
            return READ_OK, list(read(start, count)), attempts, ""
        except Exception as exc:  # noqa: BLE001 - every failure is classified
            outcome, text = classify_read_failure(exc), str(exc)
            if outcome == READ_REFUSED:
                break
            if attempts <= retries and sleep is not None and retry_delay:
                sleep(retry_delay)
    return outcome, None, attempts, text


def format_ranges_of(addresses: Iterable[int]) -> list[str]:
    """Collapse loose addresses into the ``START:END`` form the tools speak."""
    blocks = _merge_blocks((int(address), 1) for address in addresses)
    return [format_range(start, count) for start, count in blocks]


def format_range(start: int, count: int) -> str:
    """The inverse of :func:`parse_ranges`, so a map can be pasted into --range."""
    return f"0x{start:04X}:0x{start + count - 1:04X}"
