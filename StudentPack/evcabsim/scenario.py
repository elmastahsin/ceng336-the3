"""Scenario loader and validator for the simplified protocol.

Loads a JSON scenario file from disk and returns an immutable Scenario
object. 
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evcabsim.model import (
    ConFrame, DisFrame, InRunCommandFrame, LimFrame,
    ScheduledCommand, Scenario,
)


MIN_EVENT_SPACING_S = 0.100
VALID_LIM_AMPS = (0, 8, 16, 24)
VALID_PORTS    = (0, 1, 2)
LIFECYCLE_CMDS = frozenset({"GO", "END"})


class ScenarioError(ValueError):
    """Raised when a scenario file fails to load or validate."""


def load_scenario(path: str | Path) -> Scenario:
    p = Path(path)
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        raise ScenarioError(f"scenario file not readable: {p}: {e}") from e
    except json.JSONDecodeError as e:
        raise ScenarioError(f"scenario JSON parse error at {p}: {e}") from e

    if not isinstance(data, dict):
        raise ScenarioError("scenario root must be a JSON object")

    duration_s = _require_number(data, "duration_s")
    if duration_s <= 0:
        raise ScenarioError(f"duration_s must be positive, got {duration_s}")

    events_raw = data.get("events", [])
    if not isinstance(events_raw, list):
        raise ScenarioError("events must be a JSON array")
    events = tuple(_parse_event(i, e, duration_s)
                   for i, e in enumerate(events_raw))
    _validate_event_spacing(events)

    return Scenario(duration_s=float(duration_s), events=events)


def _require_number(data: dict, key: str) -> float:
    if key not in data:
        raise ScenarioError(f"missing required field: {key}")
    val = data[key]
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        raise ScenarioError(f"{key} must be a number, got {type(val).__name__}")
    return float(val)


def _parse_event(index: int, raw: Any, duration_s: float) -> ScheduledCommand:
    if not isinstance(raw, dict):
        raise ScenarioError(f"events[{index}] must be an object")
    if "t" not in raw or "cmd" not in raw:
        raise ScenarioError(f"events[{index}] requires fields 't' and 'cmd'")
    t = raw["t"]
    if not isinstance(t, (int, float)) or isinstance(t, bool):
        raise ScenarioError(f"events[{index}].t must be a number")
    t = float(t)
    if not (0.10 < t < duration_s):
        raise ScenarioError(
            f"events[{index}].t={t} must satisfy 0.10 < t < duration_s "
            f"({duration_s})")
    if int(round(t * 1000)) % 100 == 0:
        raise ScenarioError(
            f"events[{index}].t={t} falls on a 100 ms tick boundary; "
            "per main.tex §11 timestamps must arrive strictly between "
            "two ticks")
    cmd = raw["cmd"]
    if not isinstance(cmd, str):
        raise ScenarioError(f"events[{index}].cmd must be a string")
    if cmd in LIFECYCLE_CMDS:
        raise ScenarioError(
            f"events[{index}].cmd={cmd!r} is a lifecycle frame, "
            "not permitted in scenario")
    frame = _parse_cmd(cmd, index)
    return ScheduledCommand(t=t, frame=frame)


def _parse_cmd(cmd: str, index: int) -> InRunCommandFrame:
    if cmd.startswith("LIM") and len(cmd) == 5:
        try:
            amps = int(cmd[3:])
        except ValueError:
            raise ScenarioError(f"events[{index}].cmd={cmd!r}: bad LIM payload")
        if amps not in VALID_LIM_AMPS:
            raise ScenarioError(
                f"events[{index}].cmd={cmd!r}: LIM amps must be in {VALID_LIM_AMPS}")
        return LimFrame(amps=amps)
    if cmd.startswith("CON") and len(cmd) == 4:
        return ConFrame(port=_parse_port(cmd[3:], index, cmd))
    if cmd.startswith("DIS") and len(cmd) == 4:
        return DisFrame(port=_parse_port(cmd[3:], index, cmd))
    raise ScenarioError(
        f"events[{index}].cmd={cmd!r} is not a recognised in-run command")


def _parse_port(digit: str, index: int, cmd: str) -> int:
    try:
        p = int(digit)
    except ValueError:
        raise ScenarioError(f"events[{index}].cmd={cmd!r}: bad port digit")
    if p not in VALID_PORTS:
        raise ScenarioError(
            f"events[{index}].cmd={cmd!r}: port must be in {VALID_PORTS}")
    return p


def _validate_event_spacing(events: tuple[ScheduledCommand, ...]) -> None:
    for i in range(1, len(events)):
        prev, cur = events[i - 1], events[i]
        gap = cur.t - prev.t
        if gap < MIN_EVENT_SPACING_S:
            raise ScenarioError(
                f"events at t={prev.t} and t={cur.t} are spaced less "
                f"than 100 ms apart, which would cause the cabinet to "
                f"drop one command")
