"""Pure state-to-draw-instructions transform for the pygame probe UI.

Isolates the "what should be on screen" decision (animation state machine,
STS suppression, pending tracking) from the pygame painter so this layer
is unit-testable without a display.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal, Union

from evcabsim.app import UIUpdate
from evcabsim.model import (
    AckFrame, CabinetMode, ConFrame, DisFrame, Direction, EndFrame,
    GoFrame, LimFrame, RunPhase, StsFrame, TraceEvent,
)



WINDOW_W = 1280
WINDOW_H = 720
STATUS_STRIP_H = 80
HORIZON_Y = 422
TOWER_TOP_Y = STATUS_STRIP_H + 8
TOWER_BASE_Y = TOWER_TOP_Y + 320
CONSOLE_TOP_Y = 450



CAR_TWEEN_S = 0.6
CABLE_TWEEN_S = 0.5
CABLE_RETRACT_S = 0.4
GAUGE_TWEEN_S = 0.2
THERMAL_TWEEN_S = 0.09
MODE_FLASH_S = 0.4
EVENT_STRIP_MAX_LINES = 24
EVENT_STRIP_VISIBLE_LINES = 8



ColorName = Literal[
    "bg", "panel", "ok", "warn", "bad", "info", "dim", "text", "muted",
    "pill_ok", "pill_degraded", "pill_fault",
    "trace_sim", "trace_sts", "trace_evt", "trace_bad", "pulse",
    "bay_0_accent", "bay_1_accent", "bay_2_accent",
    "console_surface", "floor_dim",
    "wall_far", "wall_near", "ceiling_beam", "light_warm",
]



@dataclass(frozen=True)
class Rect:
    x: int; y: int; w: int; h: int
    fill: ColorName | None = None
    stroke: ColorName | None = None
    tag: str = ""


@dataclass(frozen=True)
class RoundedRect:
    x: int; y: int; w: int; h: int
    radius: int = 6
    fill: ColorName | None = None
    stroke: ColorName | None = None
    tag: str = ""


@dataclass(frozen=True)
class Text:
    x: int; y: int
    s: str
    color: ColorName = "text"
    size: int = 14
    bold: bool = False
    align: Literal["left", "center", "right"] = "left"
    tag: str = ""
    family: Literal["pixel", "mono"] = "pixel"


@dataclass(frozen=True)
class Circle:
    cx: int; cy: int; r: int
    fill: ColorName | None = None
    stroke: ColorName | None = None
    alpha: float = 1.0
    tag: str = ""


@dataclass(frozen=True)
class Line:
    x1: int; y1: int; x2: int; y2: int
    color: ColorName = "text"
    width: int = 1
    tag: str = ""


@dataclass(frozen=True)
class Polygon:
    points: tuple[tuple[int, int], ...]
    fill: ColorName | None = None
    stroke: ColorName | None = None
    tag: str = ""


@dataclass(frozen=True)
class Polyline:
    points: tuple[tuple[int, int], ...]
    color: ColorName = "text"
    width: int = 1
    tag: str = ""
    alpha: float = 1.0


@dataclass(frozen=True)
class Ellipse:
    cx: int
    cy: int
    rx: int
    ry: int
    fill: ColorName | None = None
    stroke: ColorName | None = None
    alpha: float = 1.0
    tag: str = ""


@dataclass(frozen=True)
class Sprite:
    """Request to blit a named sprite at (x, y) scaled to (w, h).

    """
    name: str
    x: int; y: int
    w: int; h: int
    tag: str = ""
    suppress_tags: tuple[str, ...] = ()


DrawInstruction = Union[
    Rect, RoundedRect, Text, Circle, Line, Polygon, Polyline, Ellipse, Sprite,
]



@dataclass(frozen=True)
class Tween:
    """Linear interpolation between start_v and target_v starting at start_t,
    finishing in duration_s. value(now) is pure: same input -> same output."""
    start_v: float
    target_v: float
    start_t: float
    duration_s: float

    def value(self, now: float) -> float:
        if self.duration_s <= 0.0:
            return self.target_v
        if now <= self.start_t:
            return self.start_v
        elapsed = now - self.start_t
        if elapsed >= self.duration_s:
            return self.target_v
        return self.start_v + (self.target_v - self.start_v) * (elapsed / self.duration_s)

    def retarget(self, new_target: float, now: float) -> "Tween":
        """Snapshot current displayed value as new start, retarget."""
        if new_target == self.target_v:
            return self
        return Tween(
            start_v=self.value(now),
            target_v=new_target,
            start_t=now,
            duration_s=self.duration_s,
        )



@dataclass(frozen=True)
class EventLine:
    t: float
    direction: Direction
    text: str
    color: ColorName
    kind: Literal["GO", "END", "STS", "ACK", "CMD", "BAD"]
    note: str = ""
    repeat_count: int = 1



@dataclass(frozen=True)
class AnimationState:
    bay_car: tuple[Tween, Tween, Tween]
    cable: tuple[Tween, Tween, Tween]
    gauge_eff: Tween
    gauge_level: Tween
    mode_flash_until: float | None
    last_seen_mode: CabinetMode | None
    last_seen_sts_signature: tuple | None
    event_strip: tuple[EventLine, ...]
    pending_port: tuple[bool | None, bool | None, bool | None]
    pending_limit: int | None
    last_sim_cmd: EventLine | None
    last_ack: EventLine | None
    last_sts: EventLine | None


def initial_animation_state() -> AnimationState:
    zero_car = Tween(start_v=0.0, target_v=0.0, start_t=0.0,
                     duration_s=CAR_TWEEN_S)
    zero_cable = Tween(start_v=0.0, target_v=0.0, start_t=0.0,
                       duration_s=CABLE_TWEEN_S)
    zero_gauge = Tween(start_v=0.0, target_v=0.0, start_t=0.0,
                       duration_s=GAUGE_TWEEN_S)
    zero_level = Tween(start_v=0.0, target_v=0.0, start_t=0.0,
                       duration_s=THERMAL_TWEEN_S)
    return AnimationState(
        bay_car=(zero_car, zero_car, zero_car),
        cable=(zero_cable, zero_cable, zero_cable),
        gauge_eff=zero_gauge,
        gauge_level=zero_level,
        mode_flash_until=None,
        last_seen_mode=None,
        last_seen_sts_signature=None,
        event_strip=(),
        pending_port=(None, None, None),
        pending_limit=None,
        last_sim_cmd=None,
        last_ack=None,
        last_sts=None,
    )



def compute_view(latest: UIUpdate, anim: AnimationState, now: float,
                 *, scroll_offset: int = 0
                 ) -> tuple[AnimationState, list[DrawInstruction]]:
    """Pure transform from engine state → animation update + draw list.
    """
    new_anim = _advance_animation(latest, anim, now)
    draws = _emit_draws(latest, new_anim, now,
                         scroll_offset=scroll_offset)
    return new_anim, draws


def _advance_animation(latest: UIUpdate, anim: AnimationState, now: float
                        ) -> AnimationState:
    cab = latest.cabinet_status

    new_bay_car = list(anim.bay_car)
    new_cable = list(anim.cable)
    for i in range(3):
        connected = bool(cab.connected_mask & (1 << i))
        car_v = anim.bay_car[i].value(now)
        cable_v = anim.cable[i].value(now)
        if connected:
            new_bay_car[i] = anim.bay_car[i].retarget(1.0, now)
            if car_v >= 0.7 and anim.cable[i].target_v != 1.0:
                new_cable[i] = Tween(
                    start_v=cable_v, target_v=1.0,
                    start_t=now, duration_s=CABLE_TWEEN_S,
                )
        else:
            if anim.cable[i].target_v != 0.0:
                new_cable[i] = Tween(
                    start_v=cable_v, target_v=0.0,
                    start_t=now, duration_s=CABLE_RETRACT_S,
                )
            if cable_v < 0.05:
                new_bay_car[i] = anim.bay_car[i].retarget(0.0, now)

    target_eff = float(cab.effective_limit) if cab.effective_limit is not None else 0.0
    new_gauge = anim.gauge_eff.retarget(target_eff, now)

    flash_until = anim.mode_flash_until
    last_mode = anim.last_seen_mode
    if cab.mode is not None and cab.mode != last_mode:
        if last_mode is not None:
            flash_until = now + MODE_FLASH_S
        last_mode = cab.mode
    if flash_until is not None and flash_until <= now:
        flash_until = None

    event_strip = list(anim.event_strip)
    last_sig = anim.last_seen_sts_signature
    pending_port = list(anim.pending_port)
    pending_limit = anim.pending_limit
    last_sim_cmd = anim.last_sim_cmd
    last_ack = anim.last_ack
    last_sts = anim.last_sts

    for te in latest.new_trace_events:
        line = _trace_to_event_line(te)
        if line is None:
            continue

        note_parts: list[str] = []
        sts_landed_effect = False
        if isinstance(te.parsed, AckFrame):
            if last_sim_cmd is not None:
                rtt_ms = (te.t - last_sim_cmd.t) * 1000
                note_parts.append(f"+{rtt_ms:.0f}ms")
        elif isinstance(te.parsed, StsFrame):
            if last_sts is not None:
                delta_ms = (te.t - last_sts.t) * 1000
                note_parts.append(f"Δ={delta_ms:.0f}ms")
            for i in range(3):
                if pending_port[i] is None:
                    continue
                actual = bool(te.parsed.connected_mask & (1 << i))
                if actual == pending_port[i]:
                    note_parts.append(f"→c[{i}]={1 if actual else 0}")
                    pending_port[i] = None
                    sts_landed_effect = True
            if pending_limit is not None:
                expected = _expected_ee(pending_limit, te.parsed.mode)
                if expected is not None and te.parsed.effective_limit == expected:
                    note_parts.append(f"→ee={te.parsed.effective_limit:02d}")
                    pending_limit = None
                    sts_landed_effect = True
        if note_parts:
            line = replace(line, note="  ".join(note_parts))

        if te.direction is Direction.SIM_TO_CABINET:
            if isinstance(te.parsed, ConFrame):
                pending_port[te.parsed.port] = True
            elif isinstance(te.parsed, DisFrame):
                pending_port[te.parsed.port] = False
            elif isinstance(te.parsed, LimFrame):
                pending_limit = te.parsed.amps

        if line.kind in ("CMD", "GO", "END"):
            last_sim_cmd = line
        elif line.kind == "ACK":
            last_ack = line
        elif line.kind == "STS":
            last_sts = line

        if isinstance(te.parsed, StsFrame):
            sig = (te.parsed.mode,
                   te.parsed.connected_mask, te.parsed.effective_limit)
            if (sig == last_sig
                    and event_strip
                    and event_strip[-1].kind == "STS"
                    and not sts_landed_effect):
                prev = event_strip[-1]
                event_strip[-1] = replace(
                    prev, repeat_count=prev.repeat_count + 1)
                continue
            last_sig = sig
        event_strip.append(line)

    if len(event_strip) > EVENT_STRIP_MAX_LINES:
        event_strip = event_strip[-EVENT_STRIP_MAX_LINES:]

    for i in range(3):
        if pending_port[i] is None:
            continue
        actual = bool(cab.connected_mask & (1 << i))
        if actual == pending_port[i]:
            pending_port[i] = None

    if pending_limit is not None:
        expected = _expected_ee(pending_limit, cab.mode)
        if expected is not None and cab.effective_limit == expected:
            pending_limit = None

    target_level = (cab.adc / 1023.0) if cab.adc is not None else 0.0
    new_level = anim.gauge_level.retarget(target_level, now)

    return replace(
        anim,
        bay_car=tuple(new_bay_car),
        cable=tuple(new_cable),
        gauge_eff=new_gauge,
        gauge_level=new_level,
        mode_flash_until=flash_until,
        last_seen_mode=last_mode,
        last_seen_sts_signature=last_sig,
        event_strip=tuple(event_strip),
        pending_port=tuple(pending_port),
        pending_limit=pending_limit,
        last_sim_cmd=last_sim_cmd,
        last_ack=last_ack,
        last_sts=last_sts,
    )


def _trace_to_event_line(te: TraceEvent) -> EventLine | None:
    if te.parse_error is not None:
        return EventLine(t=te.t, direction=te.direction,
                         text=f"{te.raw!r} parse error: {te.parse_error}",
                         color="trace_bad", kind="BAD")
    if isinstance(te.parsed, GoFrame):
        return EventLine(t=te.t, direction=te.direction,
                         text="GO", color="trace_sim", kind="GO")
    if isinstance(te.parsed, EndFrame):
        return EventLine(t=te.t, direction=te.direction,
                         text="END", color="trace_sim", kind="END")
    if isinstance(te.parsed, StsFrame):
        s = te.parsed
        return EventLine(
            t=te.t, direction=te.direction,
            text=(f"STS mode={s.mode.value} adc={s.adc} "
                  f"c={s.connected_mask} ee={s.effective_limit:02d}"),
            color="trace_sts", kind="STS",
        )
    if isinstance(te.parsed, AckFrame):
        code = te.parsed.code
        meaning = _ACK_MEANINGS.get(code, "?")
        return EventLine(t=te.t, direction=te.direction,
                         text=f"ACK{code:02d}  {meaning}",
                         color="trace_evt", kind="ACK")
    if isinstance(te.parsed, ConFrame):
        return EventLine(t=te.t, direction=te.direction,
                         text=f"CON{te.parsed.port}",
                         color="trace_sim", kind="CMD")
    if isinstance(te.parsed, DisFrame):
        return EventLine(t=te.t, direction=te.direction,
                         text=f"DIS{te.parsed.port}",
                         color="info", kind="CMD")
    if isinstance(te.parsed, LimFrame):
        return EventLine(t=te.t, direction=te.direction,
                         text=f"LIM{te.parsed.amps:02d}",
                         color="trace_sim", kind="CMD")
    return EventLine(t=te.t, direction=te.direction,
                     text=te.raw.decode(errors="replace"),
                     color="trace_sim", kind="CMD")



_BAND_CAP_FOR_MODE: dict[CabinetMode, int] = {
    CabinetMode.NORMAL:   24,
    CabinetMode.DERATED:  8,
    CabinetMode.OVERHEAT: 0,
}


def _expected_ee(requested_limit: int, mode: CabinetMode | None) -> int | None:
    """ee the cabinet should report for the given request + reported mode.
    Returns None if the mode is unknown (no STS yet)."""
    if mode is None:
        return None
    return min(requested_limit, _BAND_CAP_FOR_MODE[mode])



_MODE_PILL_COLOR_FOR: dict[CabinetMode, ColorName] = {
    CabinetMode.NORMAL:   "pill_ok",
    CabinetMode.DERATED:  "pill_degraded",
    CabinetMode.OVERHEAT: "pill_fault",
}


_ACK_MEANINGS: dict[int, str] = {
    0: "GO ok", 1: "CON ok", 2: "DIS ok", 3: "LIM ok",
}


_BRICK_ZONES: tuple[ColorName, ...] = (
    "wall_far",
    "bg",
    "floor_dim",
    "wall_near",
)


def _emit_back_wall(latest: UIUpdate, anim: AnimationState, now: float
                     ) -> list[DrawInstruction]:
    """Procedural brick wall behind the bay row. 
    """
    out: list[DrawInstruction] = []
    wall_top = STATUS_STRIP_H
    wall_bot = HORIZON_Y
    brick_w = 32
    brick_h = 14
    gap = 1
    row_pitch = brick_h + gap
    col_pitch = brick_w + gap

    rows_total = (wall_bot - wall_top) // row_pitch
    cols_total = WINDOW_W // col_pitch + 2
    rows_per_zone = max(1, rows_total // len(_BRICK_ZONES))

    for row in range(rows_total):
        y = wall_top + row * row_pitch
        zone_idx = min(len(_BRICK_ZONES) - 1, row // rows_per_zone)
        base_tone = _BRICK_ZONES[zone_idx]
        x_offset = (row % 2) * (brick_w // 2)
        for col in range(cols_total):
            x = col * col_pitch - x_offset
            if x + brick_w < 0 or x > WINDOW_W:
                continue
            n = (row * 7 + col * 13) % 11
            if n == 0 and zone_idx > 0:
                tone = _BRICK_ZONES[zone_idx - 1]
            elif n == 1 and zone_idx < len(_BRICK_ZONES) - 1:
                tone = _BRICK_ZONES[zone_idx + 1]
            else:
                tone = base_tone
            out.append(Rect(
                x=x, y=y, w=brick_w, h=brick_h,
                fill=tone, tag="back_wall_brick",
            ))
    return out


_CEILING_LIGHT_L_CX = 360
_CEILING_LIGHT_R_CX = 1000
_CEILING_TOP_BEAM_Y = 14
_CEILING_LOWER_BEAM_Y = 64
_CEILING_FIXTURE_BOTTOM_Y = 92


def _emit_ceiling(latest: UIUpdate, anim: AnimationState, now: float
                   ) -> list[DrawInstruction]:
    """Warehouse ceiling — beams, struts, two amber lamp fixtures with
    downward light shafts. Right-hand fixture shares an idle flicker
    multiplier with its floor pool.
    """
    out: list[DrawInstruction] = []

    out.append(Rect(
        x=0, y=_CEILING_TOP_BEAM_Y, w=WINDOW_W, h=12,
        fill="ceiling_beam", tag="ceiling_beam",
    ))
    out.append(Rect(
        x=0, y=_CEILING_LOWER_BEAM_Y, w=WINDOW_W, h=6,
        fill="ceiling_beam", tag="ceiling_beam",
    ))
    strut_w = 14
    strut_h = _CEILING_LOWER_BEAM_Y + 6 - _CEILING_TOP_BEAM_Y
    out.append(Rect(
        x=18, y=_CEILING_TOP_BEAM_Y, w=strut_w, h=strut_h,
        fill="ceiling_beam", tag="ceiling_strut_l",
    ))
    out.append(Rect(
        x=WINDOW_W - 18 - strut_w, y=_CEILING_TOP_BEAM_Y,
        w=strut_w, h=strut_h,
        fill="ceiling_beam", tag="ceiling_strut_r",
    ))
    for cx_strut in range(280, WINDOW_W - 200, 320):
        out.append(Rect(
            x=cx_strut - 3, y=_CEILING_TOP_BEAM_Y + 12,
            w=6, h=_CEILING_LOWER_BEAM_Y - _CEILING_TOP_BEAM_Y - 12,
            fill="ceiling_beam", tag="ceiling_brace",
        ))

    for cx, side, alpha_glow in (
        (_CEILING_LIGHT_L_CX, "l", 0.95),
        (_CEILING_LIGHT_R_CX, "r", 0.40),
    ):
        out.append(Rect(
            x=cx - 1, y=_CEILING_LOWER_BEAM_Y + 6,
            w=2, h=10,
            fill="ceiling_beam", tag=f"ceiling_pendant_{side}",
        ))
        housing_top_y = _CEILING_LOWER_BEAM_Y + 16
        housing_bot_y = _CEILING_FIXTURE_BOTTOM_Y
        out.append(Polygon(
            points=(
                (cx - 7,  housing_top_y),
                (cx + 7,  housing_top_y),
                (cx + 14, housing_bot_y),
                (cx - 14, housing_bot_y),
            ),
            fill="floor_dim", stroke="muted",
            tag=f"ceiling_fixture_{side}",
        ))

        bulb_cy = housing_bot_y - 2
        out.append(Circle(
            cx=cx, cy=bulb_cy, r=20,
            fill="light_warm", alpha=0.18 * alpha_glow,
            tag=f"ceiling_light_halo_outer_{side}",
        ))
        out.append(Circle(
            cx=cx, cy=bulb_cy, r=12,
            fill="light_warm", alpha=0.45 * alpha_glow,
            tag=f"ceiling_light_halo_mid_{side}",
        ))
        out.append(Circle(
            cx=cx, cy=bulb_cy, r=6,
            fill="warn", alpha=min(1.0, 0.95 * alpha_glow),
            tag=f"ceiling_light_body_{side}",
        ))
        out.append(Circle(
            cx=cx, cy=bulb_cy, r=2,
            fill="text", alpha=alpha_glow,
            tag=("ceiling_light_l" if side == "l"
                 else "ceiling_light_r_flicker"),
        ))

        for k in range(1, 6):
            shaft_cy = bulb_cy + 12 + k * 14
            shaft_r = 8 + k * 5
            shaft_alpha = (0.20 - k * 0.025) * alpha_glow
            if shaft_alpha <= 0.0:
                continue
            out.append(Circle(
                cx=cx, cy=shaft_cy, r=shaft_r,
                fill="light_warm", alpha=shaft_alpha,
                tag=f"ceiling_light_shaft_{side}",
            ))
    return out


def _emit_light_pools(latest: UIUpdate, anim: AnimationState, now: float
                       ) -> list[DrawInstruction]:
    """Warm light pools on the floor — foreshortened ellipses (rx > ry)
    that paint after the floor. Right pool is dimmer than the left to
    match its dimmer fixture, and is now static (no flicker)."""
    pool_y = HORIZON_Y + (CONSOLE_TOP_Y - HORIZON_Y) // 2
    return [
        Ellipse(
            cx=_CEILING_LIGHT_L_CX, cy=pool_y, rx=64, ry=22,
            fill="light_warm", alpha=0.22,
            tag="floor_light_cone_l",
        ),
        Ellipse(
            cx=_CEILING_LIGHT_R_CX, cy=pool_y, rx=64, ry=22,
            fill="light_warm", alpha=0.10,
            tag="floor_light_cone_r",
        ),
    ]


def _emit_status_card(latest: UIUpdate, anim: AnimationState, now: float,
                       *, x: int, y: int, w: int, h: int
                       ) -> list[DrawInstruction]:
    out: list[DrawInstruction] = []
    sim = latest.sim_state
    cab = latest.cabinet_status

    out.append(RoundedRect(
        x=x, y=y, w=w, h=h, radius=4,
        fill="panel", stroke="dim",
        tag="status_run_card",
    ))

    if sim.phase is RunPhase.WAITING:
        run_text = "WAITING"
        run_color: ColorName = "info"
    elif sim.phase is RunPhase.ACTIVE:
        elapsed = max(0.0, now - latest.go_wall_time)
        run_text = f"ACTIVE  {elapsed:.1f}s"
        run_color = "ok"
    else:
        end_t = sim.end_t if sim.end_t is not None else 0.0
        run_text = f"ENDED  {end_t:.1f}s"
        run_color = "warn"

    is_active = sim.phase is RunPhase.ACTIVE
    effective_mode = cab.mode if is_active else None
    if effective_mode is None:
        station_text = "—"
        station_color: ColorName = "dim"
    elif effective_mode is CabinetMode.NORMAL:
        station_text = "NORMAL    N"
        station_color = "ok"
    elif effective_mode is CabinetMode.DERATED:
        station_text = "DERATED   D"
        station_color = "warn"
    else:
        station_text = "OVERHEAT  H"
        station_color = "bad"

    label_size = 10
    value_size = 12
    label_x = x + 10
    value_x = x + 60
    row1_cy = y + h // 4
    row2_cy = y + 3 * h // 4

    out.append(Text(
        x=label_x, y=row1_cy - label_size // 2, s="RUN",
        color="muted", size=label_size, bold=True, align="left",
        tag="status_run_label", family="mono",
    ))
    out.append(Text(
        x=value_x, y=row1_cy - value_size // 2, s=run_text,
        color=run_color, size=value_size, bold=True, align="left",
        tag="status_run_state", family="mono",
    ))
    out.append(Text(
        x=label_x, y=row2_cy - label_size // 2, s="STATION",
        color="muted", size=label_size, bold=True, align="left",
        tag="status_station_label", family="mono",
    ))
    out.append(Text(
        x=value_x, y=row2_cy - value_size // 2, s=station_text,
        color=station_color, size=value_size, bold=True, align="left",
        tag="status_station_state", family="mono",
    ))
    return out


def _emit_floor(latest: UIUpdate, anim: AnimationState, now: float
                 ) -> list[DrawInstruction]:
    out: list[DrawInstruction] = []
    out.append(Sprite(
        name="floor_tile",
        x=0, y=HORIZON_Y, w=WINDOW_W, h=CONSOLE_TOP_Y - HORIZON_Y,
        tag="sprite_floor",
        suppress_tags=("floor_horizon", "floor_band"),
    ))
    out.append(Line(x1=0, y1=HORIZON_Y, x2=WINDOW_W, y2=HORIZON_Y,
                    color="muted", width=1, tag="floor_horizon"))
    band_h = (CONSOLE_TOP_Y - HORIZON_Y) // 4
    for k in range(4):
        out.append(Rect(x=0, y=HORIZON_Y + k * band_h, w=WINDOW_W, h=band_h,
                        fill="floor_dim" if k < 2 else "bg",
                        tag="floor_band"))
    return out


TOWER_W_BASE = 180
TOWER_W_TOP = 160
TOWER_LEFT_MARGIN = 200
TOWER_X_STEP = 320


def _tower_x(i: int) -> int:
    return TOWER_LEFT_MARGIN + i * TOWER_X_STEP


def _emit_cabinet_tower(latest: UIUpdate, anim: AnimationState, now: float,
                          i: int) -> list[DrawInstruction]:
    out: list[DrawInstruction] = []
    cab = latest.cabinet_status
    sim = latest.sim_state
    is_active = sim.phase is RunPhase.ACTIVE
    effective_mode = cab.mode if is_active else None
    cx = _tower_x(i)

    sprite_w = 130
    sprite_h = HORIZON_Y - TOWER_TOP_Y
    out.append(Sprite(
        name="cabinet_tower",
        x=cx - sprite_w // 2,
        y=TOWER_TOP_Y,
        w=sprite_w,
        h=sprite_h,
        tag=f"sprite_tower_{i}",
        suppress_tags=(
            f"tower_body_{i}", f"tower_stand_{i}",
            f"tower_screen_{i}", f"tower_modelabel_{i}",
            f"tower_socket_{i}", f"tower_hook_{i}",
        ),
    ))

    body_top_xl = cx - TOWER_W_TOP // 2
    body_top_xr = cx + TOWER_W_TOP // 2
    body_bot_xl = cx - TOWER_W_BASE // 2
    body_bot_xr = cx + TOWER_W_BASE // 2
    out.append(Polygon(
        points=((body_top_xl, TOWER_TOP_Y),
                (body_top_xr, TOWER_TOP_Y),
                (body_bot_xr, TOWER_BASE_Y),
                (body_bot_xl, TOWER_BASE_Y)),
        fill="panel", stroke="muted", tag=f"tower_body_{i}",
    ))

    stand_top_l = cx - TOWER_W_BASE // 2 - 6
    stand_top_r = cx + TOWER_W_BASE // 2 + 6
    stand_bot_l = cx - TOWER_W_BASE // 2 - 12
    stand_bot_r = cx + TOWER_W_BASE // 2 + 12
    out.append(Polygon(
        points=((stand_top_l, TOWER_BASE_Y),
                (stand_top_r, TOWER_BASE_Y),
                (stand_bot_r, TOWER_BASE_Y + 14),
                (stand_bot_l, TOWER_BASE_Y + 14)),
        fill="panel", tag=f"tower_stand_{i}",
    ))

    screen_w, screen_h = 120, 36
    screen_x = cx - screen_w // 2
    screen_y = TOWER_TOP_Y + 14
    if effective_mode is None:
        screen_fill: ColorName | None = "panel"
        screen_text = "—"
    else:
        screen_fill = _MODE_PILL_COLOR_FOR[effective_mode]
        screen_text = effective_mode.name
    out.append(RoundedRect(
        x=screen_x, y=screen_y, w=screen_w, h=screen_h, radius=4,
        fill=screen_fill, tag=f"tower_screen_{i}",
    ))
    out.append(Text(
        x=cx, y=screen_y + screen_h // 2,
        s=screen_text, color="text", size=12, bold=True, align="center",
        tag=f"tower_modelabel_{i}",
    ))

    if effective_mode is None:
        led_alpha = 0.4
        led_color: ColorName = "dim"
    elif effective_mode == CabinetMode.NORMAL:
        led_alpha = 1.0
        led_color = "ok"
    elif effective_mode == CabinetMode.OVERHEAT:
        led_alpha = 0.5 + 0.5 * math.sin(now * 1.5 * 2 * math.pi)
        led_color = "bad"
    else:
        led_alpha = 1.0
        led_color = "warn"
    badge_cx = cx + sprite_w // 2 + 18
    badge_cy = TOWER_TOP_Y + 22

    out.append(Rect(
        x=cx + sprite_w // 2 - 2, y=badge_cy - 2,
        w=20, h=4,
        fill="muted", tag=f"tower_badge_bracket_{i}",
    ))

    out.append(Circle(cx=badge_cx, cy=badge_cy, r=18, stroke=led_color,
                      alpha=led_alpha, tag=f"tower_led_{i}"))

    accent: ColorName
    if i == 0:
        accent = "bay_0_accent"
    elif i == 1:
        accent = "bay_1_accent"
    else:
        accent = "bay_2_accent"
    out.append(Circle(cx=badge_cx, cy=badge_cy, r=12, fill=accent,
                      tag=f"tower_bay_badge_{i}"))
    out.append(Text(
        x=badge_cx, y=badge_cy, s=str(i), color="text",
        size=14, bold=True, align="center",
        tag=f"tower_bay_label_{i}",
    ))

    socket_w, socket_h = 40, 24
    socket_x = cx - socket_w // 2
    socket_y = TOWER_TOP_Y + 130
    out.append(RoundedRect(
        x=socket_x, y=socket_y, w=socket_w, h=socket_h, radius=4,
        fill="bg", stroke="muted", tag=f"tower_socket_{i}",
    ))

    hook_x = socket_x + socket_w + 10
    hook_y = socket_y + socket_h // 2
    out.append(Circle(cx=hook_x, cy=hook_y, r=4, fill="muted",
                      tag=f"tower_hook_{i}"))

    if anim.pending_port[i] is not None:
        blink_alpha = 0.5
        out.append(Circle(
            cx=cx + TOWER_HOOK_X_OFFSET, cy=TOWER_HOOK_Y, r=10,
            stroke="info", alpha=blink_alpha,
            tag=f"tower_hook_blink_{i}",
        ))

    is_charging = (is_active
                   and bool(cab.connected_mask & (1 << i))
                   and (cab.effective_limit or 0) > 0)
    if is_charging:
        bolt_pulse_alpha = 0.20 + 0.30 * abs(math.sin(now * 4 * 2 * math.pi))
        bolt_cy = TOWER_TOP_Y + 174
        out.append(Circle(
            cx=cx, cy=bolt_cy, r=22,
            fill="light_warm", alpha=bolt_pulse_alpha * 0.55,
            tag=f"tower_bolt_halo_{i}",
        ))
        out.append(Circle(
            cx=cx, cy=bolt_cy, r=12,
            fill="light_warm", alpha=bolt_pulse_alpha,
            tag=f"tower_bolt_pulse_{i}",
        ))
    return out


CAR_Y_OFFSCREEN = 510
CAR_Y_PARKED = 383
CAR_W = 192
CAR_H = 78
CAR_X_OFFSET = 80
CAR_Y_FLOAT_FIX: tuple[int, int, int] = (3, 0, 13)
CABLE_PORT_OFFSET: tuple[tuple[int, int], ...] = (
    (-66, -10),
    (-54, 4),
    (-64, -11),
)

TOWER_HOOK_X_OFFSET = 60
TOWER_HOOK_Y = TOWER_TOP_Y + 100


def _bay_accent(i: int) -> "ColorName":
    if i == 0:
        return "bay_0_accent"
    if i == 1:
        return "bay_1_accent"
    return "bay_2_accent"


_CAR_SPRITE_NAMES = ("car_red", "car_blue", "car_green")


def _emit_car(latest: UIUpdate, anim: AnimationState, now: float,
              i: int) -> list[DrawInstruction]:
    progress = anim.bay_car[i].value(now)
    if progress < 0.05:
        return []
    out: list[DrawInstruction] = []

    cx = _tower_x(i) + CAR_X_OFFSET
    cy = int(CAR_Y_OFFSCREEN + (CAR_Y_PARKED - CAR_Y_OFFSCREEN) * progress)
    cy += CAR_Y_FLOAT_FIX[i]
    scale = 0.95 + 0.05 * progress
    w = int(CAR_W * scale)
    h = int(CAR_H * scale)

    accent = _bay_accent(i)

    out.append(Sprite(
        name=_CAR_SPRITE_NAMES[i],
        x=cx - w // 2, y=cy - h // 2, w=w, h=h,
        tag=f"sprite_car_{i}",
        suppress_tags=(
            f"car_body_{i}", f"car_window_{i}",
            f"car_wheel_l_{i}", f"car_wheel_r_{i}",
        ),
    ))

    out.append(RoundedRect(
        x=cx - w // 2, y=cy - h // 2, w=w, h=h, radius=10,
        fill=accent, stroke="text", tag=f"car_body_{i}",
    ))
    out.append(Rect(
        x=cx - w // 2 + 12, y=cy - h // 2 + 8, w=w - 24, h=20,
        fill="panel", tag=f"car_window_{i}",
    ))
    wheel_y = cy + h // 2 - 4
    wheel_r = max(4, h // 8)
    out.append(Circle(cx=cx - w // 4, cy=wheel_y, r=wheel_r,
                      fill="bg", stroke="text", tag=f"car_wheel_l_{i}"))
    out.append(Circle(cx=cx + w // 4, cy=wheel_y, r=wheel_r,
                      fill="bg", stroke="text", tag=f"car_wheel_r_{i}"))
    return out


def _bezier_sample(p0, p1, p2, p3, n: int = 12) -> tuple[tuple[int, int], ...]:
    out = []
    for k in range(n):
        t = k / (n - 1)
        u = 1 - t
        x = (u**3 * p0[0] + 3 * u**2 * t * p1[0]
             + 3 * u * t**2 * p2[0] + t**3 * p3[0])
        y = (u**3 * p0[1] + 3 * u**2 * t * p1[1]
             + 3 * u * t**2 * p2[1] + t**3 * p3[1])
        out.append((int(x), int(y)))
    return tuple(out)


def _emit_cable(latest: UIUpdate, anim: AnimationState, now: float,
                i: int) -> list[DrawInstruction]:
    cable_v = anim.cable[i].value(now)
    if cable_v < 0.05:
        return []
    out: list[DrawInstruction] = []
    cab = latest.cabinet_status

    tower_cx = _tower_x(i)
    car_cx = tower_cx + CAR_X_OFFSET

    p0 = (tower_cx + TOWER_HOOK_X_OFFSET, TOWER_HOOK_Y)

    car_v = anim.bay_car[i].value(now)
    car_cy = int(CAR_Y_OFFSCREEN + (CAR_Y_PARKED - CAR_Y_OFFSCREEN) * car_v)
    car_cy += CAR_Y_FLOAT_FIX[i]
    port_dx, port_dy = CABLE_PORT_OFFSET[i]
    p3_target = (car_cx + port_dx, car_cy + port_dy)

    end_x = int(p0[0] + (p3_target[0] - p0[0]) * cable_v)
    end_y = int(p0[1] + (p3_target[1] - p0[1]) * cable_v)
    p3_visible = (end_x, end_y)

    sag = 36
    p1 = (p0[0] + 4, p0[1] + sag)
    p2 = (p3_visible[0], p3_visible[1] - sag // 2)

    pts = _bezier_sample(p0, p1, p2, p3_visible, n=14)

    sim = latest.sim_state
    is_charging = (sim.phase is RunPhase.ACTIVE
                   and bool(cab.connected_mask & (1 << i))
                   and (cab.effective_limit or 0) > 0
                   and cable_v > 0.95)
    cable_color: ColorName = "ok" if is_charging else "muted"

    halo_color: ColorName = "pulse" if is_charging else "dim"
    out.append(Polyline(
        points=pts, color=halo_color, width=10, alpha=0.30,
        tag=f"cable_halo_{i}",
    ))
    out.append(Polyline(
        points=pts, color=cable_color, width=4,
        tag=f"cable_polyline_{i}",
    ))

    if is_charging:
        pulse_count = 7
        speed = 80.0
        seg_lens = [
            ((pts[k+1][0] - pts[k][0])**2
             + (pts[k+1][1] - pts[k][1])**2)**0.5
            for k in range(len(pts) - 1)
        ]
        cum_lens = [0.0]
        for sl in seg_lens:
            cum_lens.append(cum_lens[-1] + sl)
        path_len = max(1.0, cum_lens[-1])
        for j in range(pulse_count):
            base_t = j / pulse_count
            phase_jitter = (((j * 7) % 11) / 11.0 - 0.5) * 0.06
            phase = (now * speed / path_len + base_t + phase_jitter) % 1.0
            target_dist = phase * path_len
            cx_p, cy_p = pts[0]
            for k in range(len(seg_lens)):
                if cum_lens[k+1] >= target_dist:
                    frac = (target_dist - cum_lens[k]) / max(1e-6, seg_lens[k])
                    cx_p = int(pts[k][0] + (pts[k+1][0] - pts[k][0]) * frac)
                    cy_p = int(pts[k][1] + (pts[k+1][1] - pts[k][1]) * frac)
                    break
            pulse_r = 3 + ((j * 13) % 3)
            pulse_alpha = 0.65 + ((j * 17) % 7) / 25.0
            out.append(Circle(
                cx=cx_p, cy=cy_p, r=pulse_r,
                fill="pulse", alpha=pulse_alpha,
                tag=f"cable_pulse_{i}_{j}",
            ))

        spark_alpha = 0.55 + 0.45 * abs(math.sin(now * 4.0 * 2 * math.pi))
        out.append(Circle(
            cx=p3_visible[0], cy=p3_visible[1], r=10,
            fill="pulse", alpha=spark_alpha * 0.45,
            tag=f"cable_spark_outer_{i}",
        ))
        out.append(Circle(
            cx=p3_visible[0], cy=p3_visible[1], r=5,
            fill="pulse", alpha=spark_alpha,
            tag=f"cable_spark_{i}",
        ))
    return out


def _emit_console(latest: UIUpdate, anim: AnimationState, now: float,
                   *, scroll_offset: int = 0
                   ) -> list[DrawInstruction]:
    from evcabsim.probe_widgets import (
        Bolt, CRTMonitor, PlugPort, PushButton, Stepper,
    )

    out: list[DrawInstruction] = []
    sim = latest.sim_state
    cab = latest.cabinet_status

    out.append(Polygon(
        points=((0, CONSOLE_TOP_Y),
                (WINDOW_W, CONSOLE_TOP_Y),
                (WINDOW_W, WINDOW_H),
                (0, WINDOW_H)),
        fill="console_surface", tag="console_surface",
    ))
    out.append(Rect(
        x=0, y=CONSOLE_TOP_Y, w=WINDOW_W, h=2,
        fill="muted", tag="console_top_bevel",
    ))
    out.append(Rect(
        x=0, y=CONSOLE_TOP_Y + 2, w=WINDOW_W, h=2,
        fill="floor_dim", tag="console_top_shadow",
    ))

    for cx, cy in (
        (16, CONSOLE_TOP_Y + 14), (WINDOW_W - 16, CONSOLE_TOP_Y + 14),
        (16, WINDOW_H - 14), (WINDOW_W - 16, WINDOW_H - 14),
    ):
        out.extend(Bolt(cx=cx, cy=cy, r=4).draw())

    queued_port = [False, False, False]
    queued_limit = False
    for f in sim.pending_manual_frames:
        if isinstance(f, ConFrame):
            queued_port[f.port] = True
        elif isinstance(f, DisFrame):
            queued_port[f.port] = True
        elif isinstance(f, LimFrame):
            queued_limit = True
    for i in range(3):
        if anim.pending_port[i] is not None:
            queued_port[i] = True
    if anim.pending_limit is not None:
        queued_limit = True
    blink_alpha = 0.5 + 0.5 * math.sin(now * 2.0 * 2 * math.pi)

    monitor = CRTMonitor(
        x=18, y=CONSOLE_TOP_Y + 12,
        w=716, h=WINDOW_H - CONSOLE_TOP_Y - 24,
        brand="STS-OS // OPERATOR TERMINAL",
        powered=True,
    )
    out.extend(monitor.draw())

    status_card_w = 168
    status_card_h = 48
    status_card_x = monitor.screen_x + monitor.screen_w - status_card_w - 8
    status_card_y = monitor.screen_y + 8
    out.extend(_emit_status_card(
        latest, anim, now,
        x=status_card_x, y=status_card_y,
        w=status_card_w, h=status_card_h,
    ))


    line_size_loud = 14
    line_size_quiet = 12
    line_h = 16
    event_top = monitor.screen_y + 8
    event_area_h = monitor.screen_h - (event_top - monitor.screen_y) - 8
    visible_capacity = max(1, event_area_h // line_h)
    visible_lines = min(EVENT_STRIP_VISIBLE_LINES, visible_capacity)
    n = len(anim.event_strip)
    max_offset = max(0, n - visible_lines)
    clamped_offset = max(0, min(scroll_offset, max_offset))
    end_idx = n - clamped_offset
    start_idx = max(0, end_idx - visible_lines)
    lines = list(anim.event_strip)[start_idx:end_idx]

    text_x = monitor.screen_x + 10
    text_y = event_top

    if sim.phase is RunPhase.WAITING:
        header_text = "AWAITING GO — press [GO/START] or 's' to begin run"
        header_color: ColorName = "info"
    elif sim.phase is RunPhase.END:
        end_t = sim.end_t if sim.end_t is not None else 0.0
        header_text = f"WIRE TRACE — run ended at t={end_t:.1f}s"
        header_color = "warn"
    else:
        scroll_hint = (f"   [scrolled -{clamped_offset}]"
                       if clamped_offset > 0 else "")
        header_text = f"WIRE TRACE{scroll_hint}"
        header_color = "warn" if clamped_offset > 0 else "muted"
    out.append(Text(
        x=text_x, y=text_y,
        s=header_text,
        color=header_color, size=line_size_loud, bold=True, align="left",
        tag="monitor_header", family="mono",
    ))
    text_y += line_h + 4

    for el in lines:
        arrow = "→" if el.direction is Direction.SIM_TO_CABINET else "←"
        note = el.note
        if el.repeat_count > 1:
            rep = f"×{el.repeat_count}"
            note = f"{note}  {rep}" if note else rep
        text = f"{el.t:8.3f}  {arrow}  {el.text:<32}{note}"
        out.append(Text(
            x=text_x, y=text_y,
            s=text,
            color=el.color, size=line_size_quiet, bold=False, align="left",
            tag="console_lcd_line", family="mono",
        ))
        text_y += line_h
        if el.kind in ("GO", "END"):
            divider_w = max(0, status_card_x - text_x - 8)
            out.append(Rect(
                x=text_x, y=text_y,
                w=divider_w, h=1,
                fill="muted",
                tag="lifecycle_divider",
            ))
            text_y += 4

    if clamped_offset == 0:
        if sim.phase is RunPhase.ACTIVE:
            cursor_alpha = 0.4 + 0.6 * abs(math.sin(now * 1.5 * 2 * math.pi))
            out.append(Circle(
                cx=text_x + 5, cy=text_y + 6, r=5,
                fill="ok", alpha=cursor_alpha, tag="monitor_cursor",
            ))
        elif sim.phase is RunPhase.END:
            out.append(Circle(
                cx=text_x + 5, cy=text_y + 6, r=4,
                fill="dim", alpha=0.4, tag="monitor_cursor",
            ))

    if n > visible_lines:
        track_x = monitor.screen_x + monitor.screen_w - 6
        track_y = monitor.screen_y + 4
        track_h = monitor.screen_h - 8
        out.append(Rect(
            x=track_x, y=track_y, w=4, h=track_h,
            fill="floor_dim", tag="monitor_scrollbar_track",
        ))
        thumb_h = max(12, int(track_h * visible_lines / n))
        if max_offset > 0:
            thumb_y = track_y + int((track_h - thumb_h)
                                    * (max_offset - clamped_offset)
                                    / max_offset)
        else:
            thumb_y = track_y
        out.append(Rect(
            x=track_x, y=thumb_y, w=4, h=thumb_h,
            fill="muted", tag="monitor_scrollbar_thumb",
        ))

    top_cy = CONSOLE_TOP_Y + 70
    bot_cy = CONSOLE_TOP_Y + 200

    out.extend(Stepper(
        cx=860, cy=top_cy,
        value=sim.requested_limit, unit="A", label="REQ LIMIT",
        queued=queued_limit, queued_blink_alpha=blink_alpha,
        tag_down="button:limit_down", tag_up="button:limit_up",
        plate_w=240, plate_h=92,
    ).draw())

    eff_cx = 1130
    eff_w, eff_h = 180, 92
    eff_x = eff_cx - eff_w // 2
    eff_y = top_cy - eff_h // 2
    out.append(RoundedRect(
        x=eff_x, y=eff_y, w=eff_w, h=eff_h, radius=4,
        fill="console_surface", stroke="dim",
        tag="eff_limit_plate",
    ))
    for dx in (6, eff_w - 6):
        for dy in (6, eff_h - 6):
            out.append(Circle(
                cx=eff_x + dx, cy=eff_y + dy, r=2,
                fill="dim", tag="eff_limit_plate_bolt",
            ))
    out.append(Text(
        x=eff_cx, y=eff_y + 14, s="EFF LIMIT",
        color="text", size=16, bold=True, align="center",
        tag="eff_limit_label",
    ))
    eff_value = cab.effective_limit
    capped = (eff_value is not None
              and sim.requested_limit > 0
              and eff_value < sim.requested_limit)
    if eff_value is None:
        eff_text = "-- A"
        eff_color: ColorName = "dim"
    elif capped:
        eff_text = f"{eff_value:02d} A"
        eff_color = "warn"
    else:
        eff_text = f"{eff_value:02d} A"
        eff_color = "ok"
    eff_readout_y = eff_y + 32
    eff_readout_h = 36
    out.append(Rect(
        x=eff_x + 14, y=eff_readout_y,
        w=eff_w - 28, h=eff_readout_h,
        fill="bg", tag="eff_limit_readout_bg",
    ))
    out.append(Rect(
        x=eff_x + 14, y=eff_readout_y,
        w=eff_w - 28, h=eff_readout_h,
        stroke="dim", tag="eff_limit_readout_frame",
    ))
    out.append(Text(
        x=eff_cx, y=eff_readout_y + eff_readout_h // 2,
        s=eff_text,
        color=eff_color, size=22, bold=True, align="center",
        tag="eff_limit_readout",
    ))
    if capped:
        if cab.mode in (CabinetMode.DERATED, CabinetMode.OVERHEAT):
            sublabel = "THERMAL CAP"
        else:
            sublabel = "EE < REQ"
        out.append(Text(
            x=eff_cx, y=eff_y + eff_h - 10, s=sublabel,
            color="warn", size=10, bold=True, align="center",
            tag="eff_limit_capped",
        ))


    go_enabled = sim.phase is RunPhase.WAITING
    out.extend(PushButton(
        cx=782, cy=bot_cy, radius=22, label="GO / START",
        face_fill="ok", enabled=go_enabled, led_on=go_enabled,
        queued=False, queued_blink_alpha=blink_alpha,
        tag="button:go_run",
    ).draw())
    end_enabled = sim.phase is RunPhase.ACTIVE
    out.extend(PushButton(
        cx=862, cy=bot_cy, radius=22, label="END RUN",
        face_fill="bad", enabled=end_enabled, led_on=end_enabled,
        queued=False, queued_blink_alpha=blink_alpha,
        tag="button:end_run",
    ).draw())

    bay_accents: list[ColorName] = [
        "bay_0_accent", "bay_1_accent", "bay_2_accent",
    ]
    for i in range(3):
        connected = bool(cab.connected_mask & (1 << i))
        out.extend(PlugPort(
            cx=1043 + i * 86, cy=bot_cy,
            bay_index=i, bay_accent=bay_accents[i],
            connected=connected,
            queued=queued_port[i],
            queued_blink_alpha=blink_alpha,
            tag=f"button:port_{i}", radius=26,
        ).draw())


    return out


def _emit_draws(latest: UIUpdate, anim: AnimationState, now: float,
                *, scroll_offset: int = 0
                ) -> list[DrawInstruction]:
    out: list[DrawInstruction] = []
    out.append(Rect(x=0, y=0, w=WINDOW_W, h=WINDOW_H, fill="bg",
                    tag="bg_base"))
    out.extend(_emit_back_wall(latest, anim, now))
    out.extend(_emit_ceiling(latest, anim, now))
    out.extend(_emit_floor(latest, anim, now))
    out.extend(_emit_light_pools(latest, anim, now))
    for i in range(3):
        out.extend(_emit_cabinet_tower(latest, anim, now, i))
        out.extend(_emit_car(latest, anim, now, i))
        out.extend(_emit_cable(latest, anim, now, i))
    out.extend(_emit_thermal_gauge(latest, anim, now))
    out.extend(_emit_console(latest, anim, now,
                              scroll_offset=scroll_offset))
    return out


def _emit_thermal_gauge(latest: UIUpdate, anim: AnimationState, now: float
                          ) -> list[DrawInstruction]:
    from evcabsim.probe_widgets import ThermalGauge

    cab = latest.cabinet_status
    sim = latest.sim_state
    dim = sim.phase is not RunPhase.ACTIVE
    return ThermalGauge(
        cx=1110, cy=215,
        adc=cab.adc if sim.phase is RunPhase.ACTIVE else None,
        fluid_level_v=anim.gauge_level.value(now) if not dim else 0.0,
        dim=dim,
    ).draw()
