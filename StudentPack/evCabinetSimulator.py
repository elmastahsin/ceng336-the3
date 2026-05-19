#!/usr/bin/env python3
"""CENG 336 THE3 — site supervisor simulator.

Reads a JSON scenario file and plays it out over the serial link to a
PIC18F8722 cabinet controller. Displays the cabinet's reported state
in real time. 
"""

from __future__ import annotations

import argparse
import queue
import signal
import sys
import threading
from pathlib import Path
from typing import Sequence

from evcabsim.model import Scenario

SCRIPT_DIR = Path(__file__).resolve().parent


EMPTY_PROBE_SCENARIO = Scenario(
    duration_s=3600.0,
    events=(),
)


def _make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="evCabinetSimulator.py",
        description="CENG 336 THE3 site supervisor",
    )
    p.add_argument(
        "scenario",
        nargs="?",
        default=None,
        help=("path to scenario JSON. Omit for interactive empty-probe mode "
              "(--log-only without a path still loads sample_scenario.json)."),
    )
    p.add_argument("--port", default="/dev/ttyUSB0",
                   help=("serial port device (default: /dev/ttyUSB0; "
                         "override if your OS uses another name)"))
    p.add_argument("--baud", type=int, default=115200,
                   help="baud rate (default: 115200)")
    p.add_argument("--log-only", action="store_true",
                   help="no UI; print wire trace to stdout, auto-start")
    return p


def _die(msg: str, code: int) -> int:
    print(f"evCabinetSimulator: error: {msg}", file=sys.stderr)
    return code


def _resolve_scenario(args) -> Scenario:
    """Pick the scenario for this invocation.

    - explicit path -> load it
    - --log-only without a path -> sample_scenario.json (grader-stable)
    - otherwise -> in-memory empty 1-hour probe
    """
    from evcabsim.scenario import load_scenario

    if args.scenario is not None:
        return load_scenario(args.scenario)
    if args.log_only:
        return load_scenario(SCRIPT_DIR / "sample_scenario.json")
    return EMPTY_PROBE_SCENARIO


def main(argv: Sequence[str] | None = None) -> int:
    parser = _make_parser()
    args = parser.parse_args(argv)

    from evcabsim.scenario import ScenarioError

    try:
        scenario = _resolve_scenario(args)
    except ScenarioError as e:
        return _die(str(e), 2)

    return _run(scenario, args)


def _run(scenario, args) -> int:
    from evcabsim.app import App
    from evcabsim.serial_link import SerialLink
    from evcabsim.ui_log import run_log_ui

    try:
        import serial
        port = serial.Serial(args.port, args.baud, timeout=0.02)
    except Exception as e:
        return _die(f"could not open serial port {args.port}: {e}", 1)

    key_q: queue.Queue = queue.Queue()
    tx_q: queue.Queue = queue.Queue(maxsize=64)
    wire_q: queue.Queue = queue.Queue(maxsize=256)
    ui_q: queue.Queue = queue.Queue(maxsize=256)
    stop = threading.Event()
    sigint_seen = threading.Event()
    link_error = threading.Event()

    def _on_sigint(signum, frame):
        sigint_seen.set()
        stop.set()
    signal.signal(signal.SIGINT, _on_sigint)

    link = SerialLink(port, tx_q, wire_q, stop, error_event=link_error)
    app = App(scenario, key_q, tx_q, wire_q, ui_q, stop)

    link.start()
    app.start()

    exit_code = 0
    if args.log_only:
        run_log_ui(key_q, ui_q, stop)
    else:
        from evcabsim.ui_pygame import run_pygame_ui
        run_pygame_ui(key_q, ui_q, stop)

    stop.set()
    app.join(timeout=2.0)
    link.join(timeout=2.0)

    if link_error.is_set():
        exit_code = 1
    if sigint_seen.is_set():
        exit_code = 130
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
