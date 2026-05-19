"""Cadence stats tracker for cabinet-emitted frames."""

from __future__ import annotations

from evcabsim.model import StatsSnapshot


class StatsTracker:
    """Collects cabinet-frame wall times and produces StatsSnapshot.
    """

    def __init__(self) -> None:
        self._last_wall: float | None = None
        self._frame_count: int = 0
        self._interval_sum_ms: float = 0.0
        self._min_ms: float | None = None
        self._max_ms: float | None = None
        self._worst_miss_ms: float | None = None
        self._closed: bool = False
        self._late_count: int = 0

    def observe(self, wall_time: float) -> None:
        if self._closed:
            self._late_count += 1
            return
        if self._last_wall is not None:
            interval_ms = (wall_time - self._last_wall) * 1000.0
            self._interval_sum_ms += interval_ms
            self._min_ms = interval_ms if self._min_ms is None else min(self._min_ms, interval_ms)
            self._max_ms = interval_ms if self._max_ms is None else max(self._max_ms, interval_ms)
            miss = abs(interval_ms - 100.0)
            self._worst_miss_ms = miss if self._worst_miss_ms is None else max(self._worst_miss_ms, miss)
        self._last_wall = wall_time
        self._frame_count += 1

    def close_active_window(self) -> None:
        self._closed = True

    def snapshot(self) -> StatsSnapshot:
        interval_count = max(self._frame_count - 1, 0)
        avg = (self._interval_sum_ms / interval_count) if interval_count > 0 else None
        return StatsSnapshot(
            frame_count=self._frame_count,
            interval_count=interval_count,
            avg_interval_ms=avg,
            min_interval_ms=self._min_ms,
            max_interval_ms=self._max_ms,
            worst_miss_ms=self._worst_miss_ms,
            late_frame_count=self._late_count,
        )
