"""Serial I/O: port ownership, frame reassembly, worker thread.

The SerialLink thread is the sole owner of the pyserial object.  It
consumes TxRequests from tx_queue, writes them to the wire, and
produces WireEvents (both directions) on wire_event_queue.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from evcabsim.frames import DecodeError, decode_cabinet, encode
from evcabsim.model import CabinetFrame, SupervisorFrame


class FrameReassembler:
    """Accumulate bytes from the wire, emit complete $...# frames.

    Bytes outside a $...# envelope are dropped.  A new $ always restarts
    buffering.
    """

    def __init__(self) -> None:
        self._buf: bytearray = bytearray()
        self._in_frame: bool = False

    def feed(self, chunk: bytes) -> list[bytes]:
        out: list[bytes] = []
        for b in chunk:
            ch = bytes((b,))
            if ch == b"$":
                self._buf = bytearray(b"$")
                self._in_frame = True
            elif ch == b"#" and self._in_frame:
                self._buf.append(b)
                out.append(bytes(self._buf))
                self._buf = bytearray()
                self._in_frame = False
            elif self._in_frame:
                self._buf.append(b)
        return out


@dataclass(frozen=True)
class TxRequest:
    frame: SupervisorFrame


@dataclass(frozen=True)
class TxWireEvent:
    wall_time: float
    raw: bytes
    parsed: SupervisorFrame


@dataclass(frozen=True)
class RxWireEvent:
    wall_time: float
    raw: bytes
    parsed: CabinetFrame | None
    parse_error: str | None


class _SerialPort(Protocol):
    def read_until(self, terminator: bytes = b"#",
                   size: int | None = None) -> bytes: ...
    def write(self, data: bytes) -> int: ...
    def close(self) -> None: ...


MAX_TX_PER_ITER = 2


class SerialLink:
    """Owns a serial port, runs an RX/TX loop on its own thread.

    The loop:
      1. drains up to MAX_TX_PER_ITER TxRequests and writes them,
         emitting a TxWireEvent per successful write
      2. calls read_until with a short timeout and feeds the returned
         chunk into the reassembler, emitting an RxWireEvent per
         complete $...# frame
    """

    def __init__(self, port: _SerialPort,
                 tx_queue: "queue.Queue[TxRequest]",
                 wire_event_queue: "queue.Queue",
                 stop_event: threading.Event,
                 error_event: threading.Event | None = None) -> None:
        self._port = port
        self._tx_queue = tx_queue
        self._wire = wire_event_queue
        self._stop = stop_event
        self._error_event = error_event
        self._reassembler = FrameReassembler()
        self._thread: threading.Thread | None = None


    def step_once(self) -> None:
        self._drain_tx()
        self._poll_rx()

    def _drain_tx(self) -> None:
        for _ in range(MAX_TX_PER_ITER):
            try:
                req = self._tx_queue.get_nowait()
            except queue.Empty:
                return
            raw = encode(req.frame)
            self._port.write(raw)
            self._wire.put(TxWireEvent(
                wall_time=time.monotonic(), raw=raw, parsed=req.frame))

    def _poll_rx(self) -> None:
        chunk = self._port.read_until(b"#", size=64) or b""
        if not chunk:
            return
        for raw in self._reassembler.feed(chunk):
            wall = time.monotonic()
            try:
                parsed = decode_cabinet(raw)
                self._wire.put(RxWireEvent(
                    wall_time=wall, raw=raw, parsed=parsed, parse_error=None))
            except DecodeError as e:
                self._wire.put(RxWireEvent(
                    wall_time=wall, raw=raw, parsed=None, parse_error=str(e)))


    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("SerialLink already started")
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="serial_link")
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._drain_tx()
                self._poll_rx()
        except Exception:
            if self._error_event is not None:
                self._error_event.set()
            self._stop.set()
            raise
        finally:
            try:
                self._port.close()
            except Exception:
                pass
