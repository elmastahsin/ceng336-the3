"""App thread: scheduler, scenario player, state machine.

Responsibilities:
  - process KeyEvents from key_queue (START, QUIT, etc.)
  - consume TxWireEvent / RxWireEvent from wire_event_queue
  - compute due emissions (GO, scenario events, END) and put TxRequest
    on tx_queue
  - maintain SimulatorState and CabinetStatus, feed StatsTracker
  - push UIUpdate to ui_queue on state change or every 50 ms

"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from enum import Enum, auto

from evcabsim.model import (
    AckFrame, CabinetFrame, CabinetStatus, ConFrame, DisFrame, Direction,
    EndFrame, GoFrame, InRunCommandFrame, LimFrame, PortState, PortStatus,
    RunPhase, Scenario, ScheduledCommand, SimulatorState, StatsSnapshot,
    StsFrame, SupervisorFrame, TraceEvent,
)
from evcabsim.serial_link import RxWireEvent, TxRequest, TxWireEvent
from evcabsim.stats import StatsTracker


UI_MAX_IDLE_S = 0.05
MANUAL_SLOT_S = 0.100
MANUAL_QUEUE_CAP = 8


class KeyEvent(Enum):
    START           = auto()
    QUIT            = auto()
    PORT_TOGGLE_0   = auto()
    PORT_TOGGLE_1   = auto()
    PORT_TOGGLE_2   = auto()
    LIMIT_STEP_UP   = auto()
    LIMIT_STEP_DOWN = auto()
    FORCE_END       = auto()


@dataclass(frozen=True)
class UIUpdate:
    sim_state: SimulatorState
    cabinet_status: CabinetStatus
    stats: StatsSnapshot
    new_trace_events: tuple[TraceEvent, ...]
    go_wall_time: float | None = None
    next_manual_slot_t: float | None = None
    scenario_events_total: int = 0
    next_scenario_event: ScheduledCommand | None = None


logger = logging.getLogger(__name__)


def _empty_ports() -> tuple[PortState, PortState, PortState]:
    empty = PortState(status=PortStatus.EMPTY, observed_connected_since_s=None)
    return (empty, empty, empty)


def _initial_sim_state() -> SimulatorState:
    return SimulatorState(
        phase=RunPhase.WAITING, requested_limit=0, scenario_cursor=0,
        start_requested=False, pending_manual_frames=(),
    )


def _initial_cabinet_status() -> CabinetStatus:
    return CabinetStatus(
        mode=None, adc=None, effective_limit=None,
        connected_mask=0,
        ports=_empty_ports(),
        last_sts_t=None, last_ack_t=None, last_ack=None,
    )


class App:
    def __init__(
        self,
        scenario: Scenario,
        key_queue: "queue.Queue[KeyEvent]",
        tx_queue: "queue.Queue[TxRequest]",
        wire_event_queue: "queue.Queue",
        ui_queue: "queue.Queue[UIUpdate]",
        stop_event: threading.Event,
    ) -> None:
        self.scenario = scenario
        self._key_q = key_queue
        self._tx_q = tx_queue
        self._wire_q = wire_event_queue
        self._ui_q = ui_queue
        self._stop = stop_event

        self.state = _initial_sim_state()
        self.cabinet_status = _initial_cabinet_status()
        self._stats = StatsTracker()

        self._go_pending: bool = False
        self._end_pending: bool = False
        self._go_wall: float | None = None
        self._end_wall: float | None = None

        self._manual_queue: deque = deque()
        self._last_tx_wall: float | None = None

        self._new_trace: list = []
        self._all_trace: list = []
        self._ui_dirty: bool = False
        self._last_ui_push: float = 0.0

        self._thread: threading.Thread | None = None


    def _handle_keys(self) -> None:
        while True:
            try:
                ke = self._key_q.get_nowait()
            except queue.Empty:
                return
            self._dispatch_key(ke)

    def _dispatch_key(self, ke: KeyEvent) -> None:
        if ke is KeyEvent.QUIT:
            self._stop.set()
            return
        if ke is KeyEvent.START:
            if self.state.phase is RunPhase.WAITING and not self._go_pending:
                self._go_pending = True
                self.state = replace(self.state, start_requested=True)
                self._put_tx(GoFrame())
            return
        if ke is KeyEvent.FORCE_END:
            self._force_end()
            return

        if self.state.phase is not RunPhase.ACTIVE:
            return

        frame = self._build_operator_frame(ke)
        if frame is None:
            return
        if not self._enqueue_manual(frame):
            return
        if isinstance(frame, LimFrame):
            self.state = replace(self.state, requested_limit=frame.amps)

    def _build_operator_frame(self, ke: KeyEvent) -> InRunCommandFrame | None:
        if ke in (KeyEvent.PORT_TOGGLE_0, KeyEvent.PORT_TOGGLE_1,
                  KeyEvent.PORT_TOGGLE_2):
            port = {KeyEvent.PORT_TOGGLE_0: 0,
                    KeyEvent.PORT_TOGGLE_1: 1,
                    KeyEvent.PORT_TOGGLE_2: 2}[ke]
            connected = bool(self.cabinet_status.connected_mask & (1 << port))
            return DisFrame(port=port) if connected else ConFrame(port=port)
        if ke is KeyEvent.LIMIT_STEP_UP:
            steps = (0, 8, 16, 24)
            idx = (steps.index(self.state.requested_limit)
                   if self.state.requested_limit in steps else 0)
            return LimFrame(amps=steps[(idx + 1) % 4])
        if ke is KeyEvent.LIMIT_STEP_DOWN:
            steps = (0, 8, 16, 24)
            idx = (steps.index(self.state.requested_limit)
                   if self.state.requested_limit in steps else 0)
            return LimFrame(amps=steps[(idx - 1) % 4])
        return None

    def _enqueue_manual(self, frame: InRunCommandFrame) -> bool:
        if len(self._manual_queue) >= MANUAL_QUEUE_CAP:
            t_since_go = ((time.monotonic() - self._go_wall)
                          if self._go_wall is not None else 0.0)
            te = TraceEvent(
                t=t_since_go, direction=Direction.SIM_TO_CABINET,
                raw=b"", parsed=None,
                parse_error=f"manual queue full; dropped {frame!r}",
            )
            self._new_trace.append(te)
            self._all_trace.append(te)
            self._ui_dirty = True
            return False
        self._manual_queue.append(frame)
        self._sync_pending_manual()
        self._ui_dirty = True
        return True

    def _sync_pending_manual(self) -> None:
        self.state = replace(self.state,
                             pending_manual_frames=tuple(self._manual_queue))

    def _force_end(self) -> None:
        if self.state.phase is not RunPhase.ACTIVE:
            return
        if self._end_pending:
            return
        self._end_pending = True
        self._put_tx(EndFrame())
        self._end_wall = None

    def _put_tx(self, frame: SupervisorFrame) -> None:
        try:
            self._tx_q.put_nowait(TxRequest(frame=frame))
        except queue.Full:
            logger.error("tx_queue overflow on %r; aborting run", frame)
            self._stop.set()
            raise


    def _consume_wire_event(self, evt) -> None:
        t_since_go = (evt.wall_time - self._go_wall) \
                     if self._go_wall is not None else 0.0
        direction = (Direction.SIM_TO_CABINET
                     if isinstance(evt, TxWireEvent)
                     else Direction.CABINET_TO_SIM)
        te = TraceEvent(
            t=t_since_go, direction=direction, raw=evt.raw,
            parsed=evt.parsed,
            parse_error=getattr(evt, "parse_error", None),
        )
        self._new_trace.append(te)
        self._all_trace.append(te)
        self._ui_dirty = True

        if isinstance(evt, TxWireEvent):
            if isinstance(evt.parsed, GoFrame):
                self._on_go_tx_observed(evt.wall_time)
            elif isinstance(evt.parsed, EndFrame):
                self._on_end_tx_observed(evt.wall_time)
            elif isinstance(evt.parsed, LimFrame):
                self.state = replace(self.state,
                                     requested_limit=evt.parsed.amps)
                self._ui_dirty = True
            return

        if evt.parsed is None:
            return
        self._ingest_cabinet_frame(evt.parsed, evt.wall_time)

    def _ingest_cabinet_frame(self, frame: CabinetFrame, wall_time: float) -> None:
        if self.state.phase is RunPhase.ACTIVE or self.state.phase is RunPhase.END:
            self._stats.observe(wall_time)
        t_since_go = round(
            (wall_time - self._go_wall) if self._go_wall is not None else 0.0,
            6,
        )
        if isinstance(frame, StsFrame):
            self.cabinet_status = replace(
                self.cabinet_status,
                mode=frame.mode, adc=frame.adc,
                effective_limit=frame.effective_limit,
                connected_mask=frame.connected_mask,
                ports=self._derive_ports(frame, t_since_go),
                last_sts_t=t_since_go,
            )
        elif isinstance(frame, AckFrame):
            self.cabinet_status = replace(
                self.cabinet_status,
                last_ack=frame, last_ack_t=t_since_go,
            )

    def _derive_ports(self, sts: StsFrame, t_since_go: float
                      ) -> tuple[PortState, PortState, PortState]:
        result: list[PortState] = []
        prev_ports = self.cabinet_status.ports
        for i in range(3):
            connected = bool(sts.connected_mask & (1 << i))
            if not connected:
                status = PortStatus.EMPTY
                observed = None
            else:
                status = PortStatus.CONNECTED
                prev = prev_ports[i]
                observed = (prev.observed_connected_since_s
                            if prev.observed_connected_since_s is not None
                            else t_since_go)
            result.append(PortState(status=status,
                                    observed_connected_since_s=observed))
        return tuple(result)  # type: ignore[return-value]

    def _on_go_tx_observed(self, wall_time: float) -> None:
        self._go_pending = False
        self._go_wall = wall_time
        self._end_wall = wall_time + self.scenario.duration_s
        self.state = replace(self.state, phase=RunPhase.ACTIVE,
                             start_requested=False)
        self._ui_dirty = True

    def _on_end_tx_observed(self, wall_time: float) -> None:
        end_t = (wall_time - self._go_wall) if self._go_wall is not None else None
        self.state = replace(self.state, phase=RunPhase.END, end_t=end_t)
        self._end_wall = None
        self._end_pending = False
        self._stats.close_active_window()
        self._manual_queue.clear()
        self._ui_dirty = True


    def _emit_due_frames(self) -> None:
        if self.state.phase is not RunPhase.ACTIVE:
            return
        if self._end_pending:
            return
        now = time.monotonic()

        if self._end_wall is not None and self._end_wall <= now:
            self._end_wall = None
            self._end_pending = True
            self._put_tx(EndFrame())
            return

        if self._go_wall is None:
            return
        while self.state.scenario_cursor < len(self.scenario.events):
            ev = self.scenario.events[self.state.scenario_cursor]
            due = self._go_wall + ev.t
            if due > now:
                break
            if (self._last_tx_wall is not None
                    and now < self._last_tx_wall + MANUAL_SLOT_S):
                break
            self._put_tx(ev.frame)
            self._last_tx_wall = now
            self.state = replace(self.state,
                                 scenario_cursor=self.state.scenario_cursor + 1)

        while self._manual_queue:
            if (self._last_tx_wall is not None
                    and now < self._last_tx_wall + MANUAL_SLOT_S):
                break
            frame = self._manual_queue.popleft()
            self._sync_pending_manual()
            self._put_tx(frame)
            self._last_tx_wall = now


    def _push_ui_update(self) -> None:
        next_manual_slot_t: float | None = None
        if (self.state.phase is RunPhase.ACTIVE and self._go_wall is not None
                and (self._manual_queue or self._last_tx_wall is not None)):
            slot_wall = (self._last_tx_wall + MANUAL_SLOT_S
                         if self._last_tx_wall is not None
                         else time.monotonic())
            next_manual_slot_t = max(0.0, slot_wall - self._go_wall)

        next_ev: ScheduledCommand | None = None
        if self.state.scenario_cursor < len(self.scenario.events):
            next_ev = self.scenario.events[self.state.scenario_cursor]

        upd = UIUpdate(
            sim_state=self.state,
            cabinet_status=self.cabinet_status,
            stats=self._stats.snapshot(),
            new_trace_events=tuple(self._new_trace),
            go_wall_time=self._go_wall,
            next_manual_slot_t=next_manual_slot_t,
            scenario_events_total=len(self.scenario.events),
            next_scenario_event=next_ev,
        )
        self._ui_q.put(upd)
        self._new_trace.clear()
        self._ui_dirty = False
        self._last_ui_push = time.monotonic()


    def run_one_iteration(self, block_for: float | None = None) -> None:
        self._handle_keys()
        if self._stop.is_set():
            return

        try:
            evt = self._wire_q.get(timeout=block_for or UI_MAX_IDLE_S)
            self._consume_wire_event(evt)
            while True:
                try: self._consume_wire_event(self._wire_q.get_nowait())
                except queue.Empty: break
        except queue.Empty:
            pass

        self._emit_due_frames()

        now = time.monotonic()
        if self._ui_dirty or (now - self._last_ui_push) >= UI_MAX_IDLE_S:
            self._push_ui_update()


    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("App already started")
        self._thread = threading.Thread(target=self._run, daemon=True, name="app")
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self.run_one_iteration()
        except Exception:
            self._stop.set()
            raise


    @property
    def all_trace(self) -> tuple:
        """Snapshot of every TraceEvent since the run started.

        Safe to read from the main thread after `app.join()` — the App
        thread no longer mutates the list past stop_event being set.
        Returned as a tuple so callers can't mutate the App's list."""
        return tuple(self._all_trace)

    @property
    def stats_snapshot(self):
        return self._stats.snapshot()

    @property
    def go_wall(self) -> float | None:
        return self._go_wall
