"""Diegetic UI widgets for the operator console.
"""

from __future__ import annotations

from dataclasses import dataclass

from evcabsim.probe_viewmodel import (
    Circle, ColorName, DrawInstruction, Rect, RoundedRect, Text,
)



@dataclass(frozen=True)
class Bolt:
    cx: int
    cy: int
    r: int = 3
    tag: str = "console_bolt"

    def draw(self) -> list[DrawInstruction]:
        return [
            Circle(cx=self.cx, cy=self.cy, r=self.r,
                   fill="floor_dim", stroke="dim", tag=self.tag),
            Circle(cx=self.cx - 1, cy=self.cy - 1, r=max(1, self.r // 2),
                   fill="muted", tag=f"{self.tag}_glint"),
        ]



@dataclass(frozen=True)
class PushButton:
    """Round illuminated pushbutton mounted on a steel plate. 
    """
    cx: int
    cy: int
    radius: int
    label: str
    face_fill: ColorName
    enabled: bool
    led_on: bool
    queued: bool
    queued_blink_alpha: float
    tag: str
    label_size: int = 16

    @property
    def plate_w(self) -> int:
        return self.radius * 2 + 24

    @property
    def plate_h(self) -> int:
        return self.radius * 2 + 36

    @property
    def plate_x(self) -> int:
        return self.cx - self.plate_w // 2

    @property
    def plate_y(self) -> int:
        return self.cy - self.radius - 10

    def draw(self) -> list[DrawInstruction]:
        out: list[DrawInstruction] = []

        out.append(RoundedRect(
            x=self.plate_x, y=self.plate_y,
            w=self.plate_w, h=self.plate_h, radius=4,
            fill=("dim" if not self.enabled else "console_surface"),
            stroke="dim", tag=self.tag,
        ))

        for dx in (6, self.plate_w - 6):
            for dy in (6, self.plate_h - 6):
                out.append(Circle(
                    cx=self.plate_x + dx, cy=self.plate_y + dy, r=2,
                    fill="dim", tag=f"{self.tag}_plate_bolt",
                ))

        face_color = self.face_fill if self.enabled else "dim"
        out.append(Circle(
            cx=self.cx, cy=self.cy, r=self.radius + 2,
            fill="floor_dim", tag=f"{self.tag}_face_bezel",
        ))
        out.append(Circle(
            cx=self.cx, cy=self.cy, r=self.radius,
            fill=face_color, stroke="text", tag=f"{self.tag}_face",
        ))

        out.append(Circle(
            cx=self.cx - max(2, self.radius // 3),
            cy=self.cy - max(2, self.radius // 3),
            r=max(3, self.radius // 3), fill="text", alpha=0.25,
            tag=f"{self.tag}_face_highlight",
        ))

        led_cx = self.plate_x + self.plate_w - 10
        led_cy = self.plate_y + 10
        out.append(Circle(
            cx=led_cx, cy=led_cy, r=4,
            fill=(face_color if self.led_on and self.enabled else "dim"),
            alpha=(1.0 if self.led_on and self.enabled else 0.5),
            tag=f"{self.tag}_led",
        ))

        out.append(Text(
            x=self.cx, y=self.plate_y + self.plate_h - 12,
            s=self.label,
            color=("muted" if not self.enabled else "text"),
            size=self.label_size, bold=True, align="center",
            tag=f"{self.tag}_label",
        ))

        return out



@dataclass(frozen=True)
class ToggleSwitch:
    """Two-position lever switch on a mounting plate. 
    """
    cx: int
    cy: int
    label: str
    on: bool
    on_color: ColorName
    enabled: bool
    queued: bool
    queued_blink_alpha: float
    tag: str
    plate_w: int = 110
    plate_h: int = 88
    label_size: int = 16

    def draw(self) -> list[DrawInstruction]:
        out: list[DrawInstruction] = []
        plate_x = self.cx - self.plate_w // 2
        plate_y = self.cy - self.plate_h // 2

        out.append(RoundedRect(
            x=plate_x, y=plate_y, w=self.plate_w, h=self.plate_h, radius=4,
            fill=("dim" if not self.enabled else "console_surface"),
            stroke="dim", tag=self.tag,
        ))
        for dx in (6, self.plate_w - 6):
            for dy in (6, self.plate_h - 6):
                out.append(Circle(
                    cx=plate_x + dx, cy=plate_y + dy, r=2, fill="dim",
                    tag=f"{self.tag}_plate_bolt",
                ))

        out.append(Text(
            x=self.cx, y=plate_y + 14, s=self.label,
            color=("muted" if not self.enabled else "text"),
            size=self.label_size, bold=True, align="center",
            tag=f"{self.tag}_label",
        ))

        slot_w, slot_h = 56, 24
        slot_x = self.cx - slot_w // 2
        slot_y = plate_y + self.plate_h - 36
        out.append(RoundedRect(
            x=slot_x, y=slot_y, w=slot_w, h=slot_h, radius=4,
            fill="bg", stroke="dim", tag=f"{self.tag}_slot",
        ))

        thumb_w = slot_w // 2 - 3
        thumb_h = slot_h - 4
        if self.on and self.enabled:
            thumb_x = slot_x + slot_w - thumb_w - 2
            thumb_color: ColorName = self.on_color
        else:
            thumb_x = slot_x + 2
            thumb_color = "dim"
        out.append(RoundedRect(
            x=thumb_x, y=slot_y + 2, w=thumb_w, h=thumb_h, radius=2,
            fill=thumb_color, stroke="text", tag=f"{self.tag}_thumb",
        ))
        out.append(Rect(
            x=thumb_x + 2, y=slot_y + 3, w=thumb_w - 4, h=2,
            fill="text", tag=f"{self.tag}_thumb_glint",
        ))

        out.append(Text(
            x=slot_x + 6, y=slot_y - 8, s="OFF",
            color="muted", size=8, align="left",
            tag=f"{self.tag}_off_label",
        ))
        out.append(Text(
            x=slot_x + slot_w - 6, y=slot_y - 8, s="ON",
            color="muted", size=8, align="right",
            tag=f"{self.tag}_on_label",
        ))

        return out



@dataclass(frozen=True)
class Stepper:
    """Numeric stepper with -/+ buttons either side of a readout.
    """
    cx: int
    cy: int
    value: int
    unit: str
    label: str
    queued: bool
    queued_blink_alpha: float
    tag_down: str
    tag_up: str
    plate_w: int = 240
    plate_h: int = 92
    label_size: int = 16

    def draw(self) -> list[DrawInstruction]:
        out: list[DrawInstruction] = []
        plate_x = self.cx - self.plate_w // 2
        plate_y = self.cy - self.plate_h // 2

        out.append(RoundedRect(
            x=plate_x, y=plate_y, w=self.plate_w, h=self.plate_h, radius=4,
            fill="console_surface", stroke="dim",
            tag=f"{self.tag_up}_plate",
        ))
        for dx in (6, self.plate_w - 6):
            for dy in (6, self.plate_h - 6):
                out.append(Circle(
                    cx=plate_x + dx, cy=plate_y + dy, r=2, fill="dim",
                    tag=f"{self.tag_up}_plate_bolt",
                ))

        out.append(Text(
            x=self.cx, y=plate_y + 14, s=self.label,
            color="text", size=self.label_size, bold=True, align="center",
            tag=f"{self.tag_up}_section_label",
        ))

        ctrl_y = plate_y + 32
        ctrl_h = 44

        btn_w = 36
        down_x = plate_x + 14
        out.append(RoundedRect(
            x=down_x, y=ctrl_y, w=btn_w, h=ctrl_h, radius=3,
            fill="panel", stroke="dim", tag=self.tag_down,
        ))
        out.append(Text(
            x=down_x + btn_w // 2, y=ctrl_y + ctrl_h // 2,
            s="-", color="text", size=24, bold=True, align="center",
            tag=f"{self.tag_down}_label",
        ))

        up_x = plate_x + self.plate_w - 14 - btn_w
        out.append(RoundedRect(
            x=up_x, y=ctrl_y, w=btn_w, h=ctrl_h, radius=3,
            fill="panel", stroke="dim", tag=self.tag_up,
        ))
        out.append(Text(
            x=up_x + btn_w // 2, y=ctrl_y + ctrl_h // 2,
            s="+", color="text", size=24, bold=True, align="center",
            tag=f"{self.tag_up}_label",
        ))

        readout_x = down_x + btn_w + 10
        readout_w = up_x - readout_x - 10
        out.append(Rect(
            x=readout_x, y=ctrl_y, w=readout_w, h=ctrl_h,
            fill="bg", tag=f"{self.tag_up}_readout_bg",
        ))
        out.append(Rect(
            x=readout_x, y=ctrl_y, w=readout_w, h=ctrl_h,
            stroke="dim", tag=f"{self.tag_up}_readout_frame",
        ))
        out.append(Text(
            x=readout_x + readout_w // 2, y=ctrl_y + ctrl_h // 2,
            s=f"{self.value} {self.unit}",
            color="ok", size=24, bold=True, align="center",
            tag=f"{self.tag_up}_readout",
        ))

        return out



@dataclass(frozen=True)
class PlugPort:
    """Round plug-receptacle for a charging bay; click toggles plug/unplug.
    """
    cx: int
    cy: int
    bay_index: int
    bay_accent: ColorName
    connected: bool
    queued: bool
    queued_blink_alpha: float
    tag: str
    radius: int = 26
    label_size: int = 16

    @property
    def plate_w(self) -> int:
        return self.radius * 2 + 22

    @property
    def plate_h(self) -> int:
        return self.radius * 2 + 38

    @property
    def plate_x(self) -> int:
        return self.cx - self.plate_w // 2

    @property
    def plate_y(self) -> int:
        return self.cy - self.radius - 10

    def draw(self) -> list[DrawInstruction]:
        out: list[DrawInstruction] = []

        out.append(RoundedRect(
            x=self.plate_x, y=self.plate_y,
            w=self.plate_w, h=self.plate_h, radius=4,
            fill="console_surface", stroke="dim", tag=self.tag,
        ))
        for dx in (6, self.plate_w - 6):
            for dy in (6, self.plate_h - 6):
                out.append(Circle(
                    cx=self.plate_x + dx, cy=self.plate_y + dy, r=2,
                    fill="dim", tag=f"{self.tag}_plate_bolt",
                ))

        out.append(Circle(
            cx=self.cx, cy=self.cy, r=self.radius,
            fill="floor_dim", stroke="dim", tag=f"{self.tag}_rim_outer",
        ))
        out.append(Circle(
            cx=self.cx, cy=self.cy, r=self.radius - 5,
            fill=("bg" if not self.connected else self.bay_accent),
            stroke="muted", tag=f"{self.tag}_rim_inner",
        ))
        if self.connected:
            pin_color: ColorName = "bg"
            pin_r = 3
        else:
            pin_color = "muted"
            pin_r = 4
        out.append(Circle(
            cx=self.cx - 8, cy=self.cy - 4, r=pin_r,
            fill=pin_color, tag=f"{self.tag}_pin_l",
        ))
        out.append(Circle(
            cx=self.cx + 8, cy=self.cy - 4, r=pin_r,
            fill=pin_color, tag=f"{self.tag}_pin_r",
        ))
        out.append(Circle(
            cx=self.cx, cy=self.cy + 8, r=pin_r,
            fill=pin_color, tag=f"{self.tag}_pin_g",
        ))

        led_color: ColorName = self.bay_accent if self.connected else "ok"
        out.append(Circle(
            cx=self.plate_x + self.plate_w - 10,
            cy=self.plate_y + 10, r=4, fill=led_color, alpha=1.0,
            tag=f"{self.tag}_led",
        ))

        out.append(Text(
            x=self.cx, y=self.plate_y + self.plate_h - 13,
            s=f"BAY {self.bay_index}", color="text",
            size=self.label_size, bold=True, align="center",
            tag=f"{self.tag}_label",
        ))

        return out



@dataclass(frozen=True)
class CRTMonitor:
    """Bezeled CRT monitor frame. Caller supplies screen content
    separately (text lines drawn over the screen rect)."""
    x: int
    y: int
    w: int
    h: int
    brand: str
    powered: bool
    bezel_thickness: int = 14
    brand_size: int = 16
    brand_bar_h: int = 26

    @property
    def screen_x(self) -> int:
        return self.x + self.bezel_thickness

    @property
    def screen_y(self) -> int:
        return self.y + self.bezel_thickness + self.brand_bar_h + 2

    @property
    def screen_w(self) -> int:
        return self.w - 2 * self.bezel_thickness

    @property
    def screen_h(self) -> int:
        return self.h - 2 * self.bezel_thickness - self.brand_bar_h - 4

    def draw(self) -> list[DrawInstruction]:
        out: list[DrawInstruction] = []

        out.append(RoundedRect(
            x=self.x, y=self.y, w=self.w, h=self.h, radius=8,
            fill="console_surface", stroke="dim", tag="monitor_bezel",
        ))
        out.append(RoundedRect(
            x=self.x + 3, y=self.y + 3, w=self.w - 6, h=self.h - 6,
            radius=6, stroke="muted", tag="monitor_bezel_hi",
        ))

        bar_x = self.screen_x
        bar_y = self.y + self.bezel_thickness - 2
        bar_w = self.screen_w
        bar_h = self.brand_bar_h
        out.append(Rect(
            x=bar_x, y=bar_y, w=bar_w, h=bar_h,
            fill="floor_dim", tag="monitor_brand_bar",
        ))
        out.append(Rect(
            x=bar_x, y=bar_y, w=bar_w, h=bar_h,
            stroke="dim", tag="monitor_brand_bar_frame",
        ))
        out.append(Text(
            x=bar_x + 12, y=bar_y + bar_h // 2, s=self.brand,
            color="muted", size=self.brand_size, bold=True, align="left",
            tag="monitor_brand_text",
        ))
        out.append(Circle(
            cx=bar_x + bar_w - 14, cy=bar_y + bar_h // 2, r=4,
            fill=("ok" if self.powered else "dim"),
            alpha=1.0, tag="monitor_power_led",
        ))

        out.append(Rect(
            x=self.screen_x, y=self.screen_y,
            w=self.screen_w, h=self.screen_h,
            fill="bg", tag="monitor_screen",
        ))
        out.append(Rect(
            x=self.screen_x, y=self.screen_y,
            w=self.screen_w, h=self.screen_h,
            stroke="muted", tag="monitor_screen_frame",
        ))

        scan_y = self.screen_y + 2
        while scan_y < self.screen_y + self.screen_h - 1:
            out.append(Rect(
                x=self.screen_x + 1, y=scan_y,
                w=self.screen_w - 2, h=1,
                fill="floor_dim", tag="monitor_scanline",
            ))
            scan_y += 4

        for dx in (10, self.w - 10):
            for dy in (10, self.h - 10):
                out.append(Circle(
                    cx=self.x + dx, cy=self.y + dy, r=4,
                    fill="floor_dim", stroke="muted",
                    tag="monitor_bezel_bolt",
                ))

        return out



@dataclass(frozen=True)
class LabelPlate:
    """Small engraved-look plate with a centered text label."""
    cx: int
    cy: int
    text: str
    w: int = 120
    h: int = 22
    tag: str = "label_plate"

    def draw(self) -> list[DrawInstruction]:
        return [
            RoundedRect(
                x=self.cx - self.w // 2, y=self.cy - self.h // 2,
                w=self.w, h=self.h, radius=3,
                fill="floor_dim", stroke="dim", tag=self.tag,
            ),
            Text(
                x=self.cx, y=self.cy, s=self.text,
                color="muted", size=10, bold=True, align="center",
                tag=f"{self.tag}_text",
            ),
        ]


@dataclass
class ThermalGauge:
    """Vertical thermometer that visualises a 0..1023 ADC reading.
    """
    cx: int
    cy: int
    glass_w: int = 30
    glass_h: int = 220
    bulb_r: int = 22
    adc: int | None = 0
    fluid_level_v: float = 0.0
    dim: bool = False

    threshold_derated: int = 700
    threshold_overheat: int = 900

    def draw(self) -> list:
        from evcabsim.probe_viewmodel import (
            Circle, Line, Polygon, Rect, RoundedRect, Text,
        )
        out: list = []
        glass_top = self.cy - self.glass_h // 2
        glass_bot = self.cy + self.glass_h // 2
        glass_x = self.cx - self.glass_w // 2

        opacity = 0.45 if self.dim else 1.0
        bezel_w = 5
        scale_strip_w = 30
        scale_bezel_gap = 2
        scale_strip_x = glass_x - bezel_w - scale_bezel_gap - scale_strip_w

        body_left = scale_strip_x
        body_right = glass_x + self.glass_w + bezel_w
        body_mid = (body_left + body_right) // 2
        plate_w_total = 100
        plate_x = body_mid - plate_w_total // 2
        plate_y = glass_top - 18
        plate_h_total = self.glass_h + 2 * self.bulb_r + 70
        out.append(RoundedRect(
            x=plate_x, y=plate_y, w=plate_w_total, h=plate_h_total,
            radius=6, fill="panel", stroke="floor_dim",
            tag="thermal_backplate",
        ))
        for i, (sx, sy) in enumerate((
            (plate_x + 8,                 plate_y + 8),
            (plate_x + plate_w_total - 8, plate_y + 8),
            (plate_x + 8,                 plate_y + plate_h_total - 8),
            (plate_x + plate_w_total - 8, plate_y + plate_h_total - 8),
        )):
            out.append(Circle(
                cx=sx, cy=sy, r=3,
                fill="floor_dim", stroke="muted",
                tag=f"thermal_backplate_screw_{i}",
            ))
            out.append(Line(
                x1=sx - 2, y1=sy, x2=sx + 2, y2=sy,
                color="bg", width=1,
                tag=f"thermal_backplate_screw_slot_{i}",
            ))

        scale_y0 = glass_top - 4
        scale_h = self.glass_h + 8
        out.append(Rect(
            x=scale_strip_x, y=scale_y0,
            w=2, h=scale_h, fill="floor_dim",
            tag="thermal_scale_strip_shadow",
        ))
        out.append(Rect(
            x=scale_strip_x + 2, y=scale_y0,
            w=scale_strip_w - 4, h=scale_h, fill="warn",
            tag="thermal_scale_strip",
        ))
        out.append(Rect(
            x=scale_strip_x + scale_strip_w - 2, y=scale_y0,
            w=2, h=scale_h, fill="light_warm",
            tag="thermal_scale_strip_highlight",
        ))

        label_x_right = scale_strip_x + scale_strip_w - 4
        for adc_v in (200, 400, 600, 800, 1000):
            y = self._adc_to_y(adc_v, glass_top, glass_bot)
            out.append(Line(
                x1=scale_strip_x + scale_strip_w - 7, y1=y,
                x2=scale_strip_x + scale_strip_w - 2, y2=y,
                color="wall_far", width=1,
                tag=f"thermal_tick_{adc_v}",
            ))
        label_size = 16
        threshold_visual_dy = 5
        for adc_v, lbl_tag in (
            (self.threshold_derated, "thermal_tick_700"),
            (self.threshold_overheat, "thermal_tick_900"),
        ):
            y = self._adc_to_y(adc_v, glass_top, glass_bot) + threshold_visual_dy
            out.append(Text(
                x=label_x_right, y=y - label_size // 2,
                s=str(adc_v),
                color="wall_far", size=label_size, bold=True, align="right",
                tag=f"{lbl_tag}_label",
            ))

        y_at_700 = self._adc_to_y(self.threshold_derated, glass_top, glass_bot)
        y_at_900 = self._adc_to_y(self.threshold_overheat, glass_top, glass_bot)

        rail_top = glass_top - 6
        rail_h = self.glass_h + 12
        out.append(Rect(
            x=glass_x - bezel_w, y=rail_top,
            w=1, h=rail_h, fill="floor_dim",
            tag="thermal_bezel_l_shadow",
        ))
        out.append(Rect(
            x=glass_x - bezel_w + 1, y=rail_top,
            w=bezel_w - 2, h=rail_h, fill="warn",
            tag="thermal_bezel_l",
        ))
        out.append(Rect(
            x=glass_x - 1, y=rail_top,
            w=1, h=rail_h, fill="light_warm",
            tag="thermal_bezel_l_highlight",
        ))
        out.append(Rect(
            x=glass_x + self.glass_w, y=rail_top,
            w=1, h=rail_h, fill="light_warm",
            tag="thermal_bezel_r_highlight",
        ))
        out.append(Rect(
            x=glass_x + self.glass_w + 1, y=rail_top,
            w=bezel_w - 2, h=rail_h, fill="warn",
            tag="thermal_bezel_r",
        ))
        out.append(Rect(
            x=glass_x + self.glass_w + bezel_w - 1, y=rail_top,
            w=1, h=rail_h, fill="floor_dim",
            tag="thermal_bezel_r_shadow",
        ))
        out.append(Rect(
            x=glass_x - bezel_w, y=rail_top,
            w=self.glass_w + 2 * bezel_w, h=4, fill="warn",
            tag="thermal_bezel_top",
        ))
        out.append(Rect(
            x=glass_x - bezel_w, y=rail_top + 4,
            w=self.glass_w + 2 * bezel_w, h=1, fill="light_warm",
            tag="thermal_bezel_top_highlight",
        ))
        out.append(Rect(
            x=glass_x - bezel_w, y=glass_top + self.glass_h + 2,
            w=self.glass_w + 2 * bezel_w, h=4, fill="warn",
            tag="thermal_bezel_bottom",
        ))
        for i, (rx, ry) in enumerate((
            (glass_x - bezel_w + 2,                         rail_top + 2),
            (glass_x + self.glass_w + bezel_w - 3,          rail_top + 2),
            (glass_x - bezel_w + 2,                         glass_top + self.glass_h + 4),
            (glass_x + self.glass_w + bezel_w - 3,          glass_top + self.glass_h + 4),
        )):
            out.append(Circle(
                cx=rx, cy=ry, r=2,
                fill="floor_dim", tag=f"thermal_bezel_rivet_{i}",
            ))

        out.append(RoundedRect(
            x=glass_x, y=glass_top, w=self.glass_w, h=self.glass_h,
            radius=4, stroke="text",
            tag="thermal_glass",
        ))
        out.append(Rect(
            x=glass_x + 1, y=glass_top + 2,
            w=1, h=self.glass_h - 4, fill="muted",
            tag="thermal_glass_refraction",
        ))

        marker_h = 2
        strip_right_x = scale_strip_x + scale_strip_w
        marker_w = (glass_x - strip_right_x) + 3
        for adc_v, marker_tag, marker_color in (
            (self.threshold_derated, "thermal_tick_700_notch", "warn"),
            (self.threshold_overheat, "thermal_tick_900_notch", "bad"),
        ):
            y = self._adc_to_y(adc_v, glass_top, glass_bot)
            out.append(Rect(
                x=strip_right_x, y=y - marker_h // 2,
                w=marker_w, h=marker_h,
                fill=marker_color, stroke="wall_far",
                tag=marker_tag,
            ))

        if self.adc is None or self.adc < self.threshold_derated:
            fluid_color: str = "bay_2_accent"
        elif self.adc < self.threshold_overheat:
            fluid_color = "warn_deep"
        else:
            fluid_color = "bad"

        fluid_top_y = int(glass_bot - (glass_bot - glass_top) * self.fluid_level_v)
        fluid_x = glass_x + 2
        fluid_w = self.glass_w - 4
        fluid_h = max(0, glass_bot - fluid_top_y)
        out.append(Rect(
            x=fluid_x, y=fluid_top_y, w=fluid_w, h=fluid_h,
            fill=fluid_color, tag="thermal_fluid",
        ))

        if fluid_h > 0:
            out.append(Rect(
                x=fluid_x, y=fluid_top_y,
                w=fluid_w, h=min(4, fluid_h),
                fill="text", tag="thermal_fluid_meniscus",
            ))
            out.append(Rect(
                x=fluid_x, y=fluid_top_y,
                w=1, h=fluid_h,
                fill="text", tag="thermal_fluid_highlight",
            ))

        bulb_cy = glass_bot + self.bulb_r - 4
        out.append(Circle(
            cx=self.cx + 2, cy=bulb_cy + 4, r=self.bulb_r + 2,
            fill="floor_dim", alpha=0.5 * opacity,
            tag="thermal_bulb_shadow",
        ))
        out.append(Circle(
            cx=self.cx, cy=bulb_cy, r=self.bulb_r,
            fill="bad", stroke="text", alpha=opacity,
            tag="thermal_bulb",
        ))
        if not self.dim:
            out.append(Circle(
                cx=self.cx - 2, cy=bulb_cy - 2,
                r=int(self.bulb_r * 0.65),
                fill="warn", alpha=0.35,
                tag="thermal_bulb_highlight_fill",
            ))
            out.append(Circle(
                cx=self.cx - self.bulb_r // 3,
                cy=bulb_cy - self.bulb_r // 3,
                r=max(2, self.bulb_r // 5),
                fill="text", alpha=0.85,
                tag="thermal_bulb_highlight",
            ))

        if self.adc is None:
            readout_text = "----"
            readout_color: str = "dim"
        else:
            readout_text = f"{self.adc:04d}"
            readout_color = "dim" if self.dim else "text"
        out.append(Text(
            x=self.cx, y=bulb_cy + self.bulb_r + 12,
            s=readout_text,
            color=readout_color, size=14, bold=True, align="center",
            tag="thermal_readout",
        ))

        plate_y0 = bulb_cy + self.bulb_r + 26
        plate_w_brass = 96
        plate_h_brass = 18
        plate_x0 = body_mid - plate_w_brass // 2
        out.append(RoundedRect(
            x=plate_x0, y=plate_y0, w=plate_w_brass, h=plate_h_brass,
            radius=2, fill="warn", stroke="floor_dim",
            tag="thermal_nameplate",
        ))
        out.append(Rect(
            x=plate_x0 + 2, y=plate_y0 + 1,
            w=plate_w_brass - 4, h=1, fill="light_warm",
            tag="thermal_nameplate_top_highlight",
        ))
        out.append(Rect(
            x=plate_x0 + 2, y=plate_y0 + plate_h_brass - 2,
            w=plate_w_brass - 4, h=1, fill="floor_dim",
            tag="thermal_nameplate_bottom_shadow",
        ))
        out.append(Text(
            x=plate_x0 + plate_w_brass // 2,
            y=plate_y0 + plate_h_brass // 2,
            s="THERMAL · AN12",
            color="bg", size=10, bold=True, align="center",
            tag="thermal_nameplate_text",
        ))
        return out

    @staticmethod
    def _adc_to_y(adc: int, glass_top: int, glass_bot: int) -> int:
        f = max(0, min(1023, adc)) / 1023.0
        return int(glass_bot - (glass_bot - glass_top) * f)
