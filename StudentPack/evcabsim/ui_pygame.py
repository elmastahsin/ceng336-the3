"""pygame driver: paint draw instructions, pump events.

This module is intentionally thin. All layout, animation, and color logic
live in `evcabsim.probe_viewmodel`. Here we only:
  - initialize pygame
  - render a list of DrawInstruction items to a Surface
  - translate pygame events into KeyEvent on key_queue
  - tick at 60 FPS until stop_event is set
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from dataclasses import replace
from pathlib import Path

import pygame
import pygame.freetype

from evcabsim.app import KeyEvent, UIUpdate
from evcabsim.model import TraceEvent
from evcabsim.probe_viewmodel import (
    AnimationState, Circle, DrawInstruction, Ellipse,
    EVENT_STRIP_VISIBLE_LINES,
    Line, Polygon, Polyline, Rect, RoundedRect,
    Sprite, Text, WINDOW_H, WINDOW_W, compute_view, initial_animation_state,
)
from evcabsim.sprites import load_sprites


_COLORS: dict[str, tuple[int, int, int]] = {
    "bg":             (0x14, 0x16, 0x1f),
    "panel":          (0x1e, 0x21, 0x2e),
    "ok":             (0x3e, 0xcf, 0x8e),
    "warn":           (0xf5, 0xa6, 0x23),
    "bad":            (0xef, 0x44, 0x44),
    "warn_deep":      (0xea, 0x58, 0x0c),
    "info":           (0x3b, 0x82, 0xf6),
    "dim":            (0x6b, 0x72, 0x80),
    "text":           (0xe5, 0xe7, 0xeb),
    "muted":          (0x9c, 0xa3, 0xaf),
    "pill_ok":        (0x06, 0x6f, 0x4a),
    "pill_degraded":  (0x92, 0x40, 0x0e),
    "pill_fault":     (0x7f, 0x1d, 0x1d),
    "trace_sim":      (0x67, 0xe8, 0xf9),
    "trace_sts":      (0x3e, 0xcf, 0x8e),
    "trace_evt":      (0xf5, 0xa6, 0x23),
    "trace_bad":      (0xef, 0x44, 0x44),
    "pulse":          (0x86, 0xef, 0xac),
    "bay_0_accent":   (0xef, 0x44, 0x44),
    "bay_1_accent":   (0x3b, 0x82, 0xf6),
    "bay_2_accent":   (0x3e, 0xcf, 0x8e),
    "console_surface": (0x22, 0x26, 0x36),
    "floor_dim":       (0x18, 0x1b, 0x26),
    "wall_far":        (0x10, 0x12, 0x18),
    "wall_near":       (0x1c, 0x1f, 0x2a),
    "ceiling_beam":    (0x08, 0x0a, 0x10),
    "light_warm":      (0xf0, 0xa0, 0x40),
}


def _color(name: str | None) -> tuple[int, int, int] | None:
    if name is None:
        return None
    return _COLORS.get(name, _COLORS["text"])



def _load_font(font_dir: Path, size: int, *, bold: bool = False):
    """Bundled pixel font (kenney_pixel.ttf) for the warehouse / panel
    chrome — the retro look reads as deliberate. Falls back to system
    sans-serif when the asset is missing.
    """
    pixel_path = font_dir / "kenney_pixel.ttf"
    if pixel_path.exists():
        try:
            f = pygame.freetype.Font(str(pixel_path), size)
            f.antialiased = False
            return f
        except Exception:
            pass
    return pygame.freetype.SysFont("dejavusans", size, bold=bold)


def _load_mono_font(size: int, *, bold: bool = False):
    """Antialiased monospace for the operator terminal. The pixel font
    rendered too thin at the high-density frame-breakdown sizes used
    inside the terminal (STS m/adc/c/ee fields, ACK codes, trace
    timestamps); a code-style mono font keeps wire content readable
    while leaving the rest of the UI in the bundled pixel font.
    """
    for family in ("dejavusansmono", "consolas", "monospace"):
        try:
            return pygame.freetype.SysFont(family, size, bold=bold)
        except Exception:
            continue
    return pygame.freetype.SysFont(None, size, bold=bold)



BUTTON_KEY_MAP: dict[str, KeyEvent] = {
    "button:go_run":     KeyEvent.START,
    "button:end_run":    KeyEvent.FORCE_END,
    "button:port_0":     KeyEvent.PORT_TOGGLE_0,
    "button:port_1":     KeyEvent.PORT_TOGGLE_1,
    "button:port_2":     KeyEvent.PORT_TOGGLE_2,
    "button:limit_down": KeyEvent.LIMIT_STEP_DOWN,
    "button:limit_up":   KeyEvent.LIMIT_STEP_UP,
}


def _map_key(key: int, unicode: str) -> KeyEvent | None:
    if key == pygame.K_s: return KeyEvent.START
    if key in (pygame.K_q, pygame.K_ESCAPE): return KeyEvent.QUIT
    if key == pygame.K_0: return KeyEvent.PORT_TOGGLE_0
    if key == pygame.K_1: return KeyEvent.PORT_TOGGLE_1
    if key == pygame.K_2: return KeyEvent.PORT_TOGGLE_2
    if key == pygame.K_RIGHTBRACKET: return KeyEvent.LIMIT_STEP_UP
    if key == pygame.K_LEFTBRACKET:  return KeyEvent.LIMIT_STEP_DOWN
    return None


def _extract_button_regions(draws):
    """Walk the draw list for RoundedRect items whose tag is in
    BUTTON_KEY_MAP. Return [(pygame.Rect, KeyEvent), ...]. Disabled
    buttons (fill == "dim") are skipped so [END] gray-out blocks clicks.
    """
    regions = []
    for d in draws:
        if not isinstance(d, RoundedRect):
            continue
        ke = BUTTON_KEY_MAP.get(d.tag)
        if ke is None:
            continue
        if d.fill == "dim":
            continue
        regions.append((pygame.Rect(d.x, d.y, d.w, d.h), ke))
    return regions


def _hit_test(regions, pos):
    for rect, ke in regions:
        if rect.collidepoint(pos):
            return ke
    return None


def _compute_blit_geometry(window_w: int, window_h: int
                            ) -> tuple[float, int, int, int, int]:
    """Uniform aspect-preserving scale + centred letterbox for fitting
    the 1280×720 logical surface into the actual window. Returns
    `(scale, content_w, content_h, offset_x, offset_y)`.
    """
    if window_w <= 0 or window_h <= 0:
        scale = 1.0
    else:
        scale = min(window_w / WINDOW_W, window_h / WINDOW_H)
    content_w = max(1, int(WINDOW_W * scale))
    content_h = max(1, int(WINDOW_H * scale))
    offset_x = (window_w - content_w) // 2
    offset_y = (window_h - content_h) // 2
    return scale, content_w, content_h, offset_x, offset_y


def _window_to_logical(pos: tuple[int, int],
                       window_w: int, window_h: int
                       ) -> tuple[int, int]:
    """Inverse of `_compute_blit_geometry`'s scale+offset: map a physical
    mouse position into logical 1280×720 space for hit-testing."""
    scale, _, _, offset_x, offset_y = _compute_blit_geometry(window_w, window_h)
    if scale <= 0:
        return pos
    return (
        int((pos[0] - offset_x) / scale),
        int((pos[1] - offset_y) / scale),
    )



def _paint(surface, instruction, font_default, font_mono, font_big,
            font_mono_bold=None):
    if isinstance(instruction, Rect):
        if instruction.fill is not None:
            pygame.draw.rect(
                surface, _color(instruction.fill),
                pygame.Rect(instruction.x, instruction.y, instruction.w, instruction.h),
            )
        if instruction.stroke is not None:
            pygame.draw.rect(
                surface, _color(instruction.stroke),
                pygame.Rect(instruction.x, instruction.y, instruction.w, instruction.h),
                width=1,
            )
        return
    if isinstance(instruction, RoundedRect):
        rect = pygame.Rect(instruction.x, instruction.y, instruction.w, instruction.h)
        if instruction.fill is not None:
            pygame.draw.rect(surface, _color(instruction.fill), rect,
                             border_radius=instruction.radius)
        if instruction.stroke is not None:
            pygame.draw.rect(surface, _color(instruction.stroke), rect,
                             width=1, border_radius=instruction.radius)
        return
    if isinstance(instruction, Text):
        if getattr(instruction, "family", "pixel") == "mono":
            font = (font_mono_bold if (instruction.bold and font_mono_bold)
                    else font_mono)
        else:
            font = font_big if instruction.size >= 20 else font_default
        font.size = instruction.size
        text_surf, text_rect = font.render(instruction.s, _color(instruction.color))
        if instruction.align == "center":
            text_rect.center = (instruction.x, instruction.y)
        elif instruction.align == "right":
            text_rect.topright = (instruction.x, instruction.y)
        else:
            text_rect.topleft = (instruction.x, instruction.y)
        surface.blit(text_surf, text_rect)
        return
    if isinstance(instruction, Circle):
        if instruction.alpha >= 1.0:
            if instruction.fill is not None:
                pygame.draw.circle(surface, _color(instruction.fill),
                                   (instruction.cx, instruction.cy), instruction.r)
            if instruction.stroke is not None:
                pygame.draw.circle(surface, _color(instruction.stroke),
                                   (instruction.cx, instruction.cy), instruction.r,
                                   width=1)
        else:
            size = instruction.r * 2 + 2
            tmp = pygame.Surface((size, size), pygame.SRCALPHA)
            alpha255 = max(0, min(255, int(instruction.alpha * 255)))
            if instruction.fill is not None:
                r, g, b = _color(instruction.fill)
                pygame.draw.circle(tmp, (r, g, b, alpha255),
                                   (instruction.r + 1, instruction.r + 1),
                                   instruction.r)
            if instruction.stroke is not None:
                r, g, b = _color(instruction.stroke)
                pygame.draw.circle(tmp, (r, g, b, alpha255),
                                   (instruction.r + 1, instruction.r + 1),
                                   instruction.r, width=1)
            surface.blit(tmp, (instruction.cx - instruction.r - 1,
                               instruction.cy - instruction.r - 1))
        return
    if isinstance(instruction, Line):
        pygame.draw.line(surface, _color(instruction.color),
                         (instruction.x1, instruction.y1),
                         (instruction.x2, instruction.y2),
                         width=instruction.width)
        return
    if isinstance(instruction, Polygon):
        pts = list(instruction.points)
        if instruction.fill is not None:
            pygame.draw.polygon(surface, _color(instruction.fill), pts)
        if instruction.stroke is not None:
            pygame.draw.polygon(surface, _color(instruction.stroke), pts, width=1)
        return
    if isinstance(instruction, Polyline):
        pts = list(instruction.points)
        if len(pts) < 2:
            return
        if instruction.alpha >= 1.0:
            pygame.draw.lines(surface, _color(instruction.color), False, pts,
                              width=instruction.width)
        else:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            pad = instruction.width + 2
            tw = max_x - min_x + 2 * pad
            th = max_y - min_y + 2 * pad
            tmp = pygame.Surface((tw, th), pygame.SRCALPHA)
            offset_pts = [(p[0] - min_x + pad, p[1] - min_y + pad) for p in pts]
            r, g, b = _color(instruction.color)
            alpha255 = max(0, min(255, int(instruction.alpha * 255)))
            pygame.draw.lines(tmp, (r, g, b, alpha255), False, offset_pts,
                              width=instruction.width)
            surface.blit(tmp, (min_x - pad, min_y - pad))
        return
    if isinstance(instruction, Ellipse):
        rect = pygame.Rect(
            instruction.cx - instruction.rx, instruction.cy - instruction.ry,
            instruction.rx * 2, instruction.ry * 2,
        )
        if instruction.alpha >= 1.0:
            if instruction.fill is not None:
                pygame.draw.ellipse(surface, _color(instruction.fill), rect)
            if instruction.stroke is not None:
                pygame.draw.ellipse(surface, _color(instruction.stroke),
                                    rect, width=1)
        else:
            tw = instruction.rx * 2 + 2
            th = instruction.ry * 2 + 2
            tmp = pygame.Surface((tw, th), pygame.SRCALPHA)
            local_rect = pygame.Rect(1, 1, instruction.rx * 2, instruction.ry * 2)
            alpha255 = max(0, min(255, int(instruction.alpha * 255)))
            if instruction.fill is not None:
                r, g, b = _color(instruction.fill)
                pygame.draw.ellipse(tmp, (r, g, b, alpha255), local_rect)
            if instruction.stroke is not None:
                r, g, b = _color(instruction.stroke)
                pygame.draw.ellipse(tmp, (r, g, b, alpha255),
                                    local_rect, width=1)
            surface.blit(tmp, (instruction.cx - instruction.rx - 1,
                               instruction.cy - instruction.ry - 1))
        return


def _waiting_draws() -> list[DrawInstruction]:
    """Frame contents to render before the first UIUpdate arrives."""
    return [
        Rect(x=0, y=0, w=WINDOW_W, h=WINDOW_H, fill="bg", tag="bg"),
        Text(x=WINDOW_W // 2, y=WINDOW_H // 2,
             s="waiting for first UI update...",
             color="muted", size=16, align="center", tag="waiting"),
    ]


def _blit_sprite(screen, sprite_surf, instruction: Sprite) -> None:
    """Blit a Sprite instruction's surface to `screen`. `floor_tile` is
    repeated horizontally; everything else is straight-scaled."""
    if instruction.name == "floor_tile":
        tile_h = max(1, instruction.h)
        src_w = max(1, sprite_surf.get_width())
        src_h = max(1, sprite_surf.get_height())
        tile_w = max(1, src_w * tile_h // src_h)
        scaled = pygame.transform.scale(sprite_surf, (tile_w, tile_h))
        x = instruction.x
        end_x = instruction.x + instruction.w
        while x < end_x:
            screen.blit(scaled, (x, instruction.y))
            x += tile_w
    else:
        scaled = pygame.transform.scale(
            sprite_surf, (max(1, instruction.w), max(1, instruction.h)),
        )
        screen.blit(scaled, (instruction.x, instruction.y))


def run_pygame_ui(
    key_queue: "queue.Queue[KeyEvent]",
    ui_queue: "queue.Queue[UIUpdate]",
    stop_event: threading.Event,
    *,
    sprites_disabled: bool = False,
) -> None:
    pygame.init()
    pygame.freetype.init()
    window_w, window_h = WINDOW_W, WINDOW_H
    screen = pygame.display.set_mode(
        (window_w, window_h), pygame.RESIZABLE,
    )
    render_surface = pygame.Surface((WINDOW_W, WINDOW_H))
    pygame.display.set_caption("EV Cabinet Supervisor")
    fonts_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    font_default = _load_font(fonts_dir, 16)
    font_big = _load_font(fonts_dir, 24, bold=True)
    font_mono = _load_mono_font(16)
    font_mono_bold = _load_mono_font(16, bold=True)

    assets_dir = Path(__file__).resolve().parent.parent / "assets"
    sprites = load_sprites(assets_dir, disabled=sprites_disabled)

    clock = pygame.time.Clock()
    anim = initial_animation_state()
    latest: UIUpdate | None = None
    button_regions: list = []
    event_scroll_offset = 0

    try:
        while not stop_event.is_set():
            drained_events: list[TraceEvent] = []
            while True:
                try:
                    upd = ui_queue.get_nowait()
                except queue.Empty:
                    break
                drained_events.extend(upd.new_trace_events)
                latest = upd
            if latest is not None and drained_events:
                latest = replace(latest,
                                 new_trace_events=tuple(drained_events))

            for ev in pygame.event.get():
                if ev.type == pygame.VIDEORESIZE:
                    window_w, window_h = ev.w, ev.h
                    screen = pygame.display.get_surface()
                    continue
                if ev.type == pygame.QUIT:
                    stop_event.set()
                    key_queue.put(KeyEvent.QUIT)
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_PAGEUP:
                        event_scroll_offset += 5
                        continue
                    if ev.key == pygame.K_PAGEDOWN:
                        event_scroll_offset = max(0, event_scroll_offset - 5)
                        continue
                    if ev.key == pygame.K_HOME:
                        event_scroll_offset = 10**6
                        continue
                    if ev.key == pygame.K_END:
                        event_scroll_offset = 0
                        continue
                    ke = _map_key(ev.key, ev.unicode)
                    if ke is not None:
                        key_queue.put(ke)
                elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    logical_pos = _window_to_logical(
                        ev.pos, window_w, window_h,
                    )
                    hit = _hit_test(button_regions, logical_pos)
                    if hit is not None:
                        key_queue.put(hit)
                elif ev.type == pygame.MOUSEWHEEL:
                    event_scroll_offset = max(
                        0, event_scroll_offset + ev.y
                    )

            buffer_n = len(anim.event_strip)
            max_offset_estimate = max(0, buffer_n - EVENT_STRIP_VISIBLE_LINES)
            event_scroll_offset = max(
                0, min(event_scroll_offset, max_offset_estimate)
            )

            if latest is not None:
                anim, draws = compute_view(
                    latest, anim, time.monotonic(),
                    scroll_offset=event_scroll_offset,
                )
                button_regions = _extract_button_regions(draws)
                if latest.new_trace_events:
                    latest = replace(latest, new_trace_events=())
            else:
                draws = _waiting_draws()
                button_regions = []

            suppressed_tags: set[str] = set()
            for d in draws:
                if isinstance(d, Sprite) and d.name in sprites:
                    suppressed_tags.update(d.suppress_tags)

            render_surface.fill(_color("bg"))
            for d in draws:
                if isinstance(d, Text):
                    continue
                if isinstance(d, Sprite):
                    surf = sprites.get(d.name)
                    if surf is not None:
                        _blit_sprite(render_surface, surf, d)
                    continue
                if getattr(d, "tag", "") in suppressed_tags:
                    continue
                _paint(render_surface, d, font_default, font_mono,
                       font_big, font_mono_bold)

            scale, content_w, content_h, offset_x, offset_y = (
                _compute_blit_geometry(window_w, window_h)
            )
            screen.fill(_color("bg"))
            if content_w == WINDOW_W and content_h == WINDOW_H:
                screen.blit(render_surface, (offset_x, offset_y))
            else:
                scaled = pygame.transform.scale(
                    render_surface, (content_w, content_h),
                )
                screen.blit(scaled, (offset_x, offset_y))

            for d in draws:
                if not isinstance(d, Text):
                    continue
                if getattr(d, "tag", "") in suppressed_tags:
                    continue
                if getattr(d, "family", "pixel") == "mono":
                    font = font_mono_bold if d.bold else font_mono
                else:
                    font = font_big if d.size >= 20 else font_default
                font.size = max(8, int(round(d.size * scale)))
                text_surf, text_rect = font.render(d.s, _color(d.color))
                sx = int(d.x * scale + offset_x)
                sy = int(d.y * scale + offset_y)
                if d.align == "center":
                    text_rect.center = (sx, sy)
                elif d.align == "right":
                    text_rect.topright = (sx, sy)
                else:
                    text_rect.topleft = (sx, sy)
                screen.blit(text_surf, text_rect)

            pygame.display.flip()
            clock.tick(60)
    finally:
        pygame.quit()
