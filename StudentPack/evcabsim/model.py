"""Data model for the simplified EV cabinet simulator.

All types here are plain containers — no behaviour. 
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Union


class Direction(Enum):
    SIM_TO_CABINET = "sim"
    CABINET_TO_SIM = "pic"


class CabinetMode(Enum):
    NORMAL   = "N"
    DERATED  = "D"
    OVERHEAT = "H"


class PortStatus(Enum):
    EMPTY     = auto()
    CONNECTED = auto()


class RunPhase(Enum):
    WAITING = auto()
    ACTIVE  = auto()
    END     = auto()



@dataclass(frozen=True)
class GoFrame:
    pass


@dataclass(frozen=True)
class EndFrame:
    pass


@dataclass(frozen=True)
class LimFrame:
    amps: int


@dataclass(frozen=True)
class ConFrame:
    port: int


@dataclass(frozen=True)
class DisFrame:
    port: int


@dataclass(frozen=True)
class StsFrame:
    mode: CabinetMode
    adc: int
    connected_mask: int
    effective_limit: int


@dataclass(frozen=True)
class AckFrame:
    code: int



InRunCommandFrame = Union[ConFrame, DisFrame, LimFrame]
SupervisorFrame   = Union[GoFrame, EndFrame, ConFrame, DisFrame, LimFrame]
CabinetFrame      = Union[StsFrame, AckFrame]
WireFrame         = Union[SupervisorFrame, CabinetFrame]



@dataclass(frozen=True)
class TraceEvent:
    t: float
    direction: Direction
    raw: bytes
    parsed: WireFrame | None
    parse_error: str | None = None



@dataclass(frozen=True)
class ScheduledCommand:
    t: float
    frame: InRunCommandFrame


@dataclass(frozen=True)
class Scenario:
    duration_s: float
    events: tuple[ScheduledCommand, ...] = ()



@dataclass(frozen=True)
class PortState:
    status: PortStatus
    observed_connected_since_s: float | None


@dataclass(frozen=True)
class CabinetStatus:
    mode: CabinetMode | None
    adc: int | None
    effective_limit: int | None
    connected_mask: int
    ports: tuple[PortState, PortState, PortState]
    last_sts_t: float | None
    last_ack_t: float | None
    last_ack: AckFrame | None


@dataclass(frozen=True)
class SimulatorState:
    phase: RunPhase
    requested_limit: int
    scenario_cursor: int
    start_requested: bool
    pending_manual_frames: tuple[InRunCommandFrame, ...] = ()
    end_t: float | None = None



@dataclass(frozen=True)
class StatsSnapshot:
    frame_count: int
    interval_count: int
    avg_interval_ms: float | None
    min_interval_ms: float | None
    max_interval_ms: float | None
    worst_miss_ms: float | None
    late_frame_count: int
