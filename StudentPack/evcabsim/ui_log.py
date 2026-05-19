"""Log-only UI: 

In this mode the simulator auto-starts at launch, drains the wire to
completion of the scenario, prints a stats summary, and exits. 

"""

from __future__ import annotations

import queue
import sys
import threading
import time
from typing import TextIO

from evcabsim.app import KeyEvent, UIUpdate
from evcabsim.model import Direction, RunPhase, StatsSnapshot, TraceEvent


POST_END_DRAIN_S = 0.500


def format_trace_event(te: TraceEvent) -> str:
    dir_str = "sim" if te.direction is Direction.SIM_TO_CABINET else "pic"
    time_field = f"t={te.t:<5.2f}"
    line = f"{time_field:<8} {dir_str} -> {te.raw.decode('ascii', errors='replace')}"
    if te.parse_error:
        line += f"                (malformed: {te.parse_error})"
    return line


def format_stats_summary(s: StatsSnapshot) -> str:
    parts = [f"count {s.frame_count}"]
    if s.interval_count > 0 and s.avg_interval_ms is not None:
        parts.append(f"avg {s.avg_interval_ms:.1f} ms")
        if s.min_interval_ms is not None:
            parts.append(f"min {s.min_interval_ms:.1f} ms")
        if s.max_interval_ms is not None:
            parts.append(f"max {s.max_interval_ms:.1f} ms")
    if s.late_frame_count > 0:
        parts.append(f"late {s.late_frame_count}")
    return "  ".join(parts)


def run_log_ui(
    key_queue: "queue.Queue",
    ui_queue: "queue.Queue[UIUpdate]",
    stop_event: threading.Event,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> None:
    key_queue.put(KeyEvent.START)

    latest: UIUpdate | None = None
    end_seen_at: float | None = None

    while not stop_event.is_set():
        try:
            upd = ui_queue.get(timeout=0.05)
        except queue.Empty:
            upd = None

        if upd is not None:
            latest = upd
            for te in upd.new_trace_events:
                out.write(format_trace_event(te) + "\n")
                out.flush()
            if upd.sim_state.phase is RunPhase.END and end_seen_at is None:
                end_seen_at = time.monotonic()

        if end_seen_at is not None:
            if time.monotonic() - end_seen_at >= POST_END_DRAIN_S:
                break

    if latest is not None:
        err.write(format_stats_summary(latest.stats) + "\n")
        err.flush()
    stop_event.set()
