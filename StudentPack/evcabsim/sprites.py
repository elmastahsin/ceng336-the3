"""Optional sprite asset loading. 
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


SPRITE_MANIFEST: dict[str, tuple[str, tuple[int, int]]] = {
    "cabinet_tower": ("cabinet_tower_cropped.png", (130, 334)),
    "car_red":       ("car_red_cropped.png", (192, 78)),
    "car_blue":      ("car_blue_cropped.png", (192, 78)),
    "car_green":     ("car_green_cropped.png", (192, 78)),
    "floor_tile":    ("floor_tile.png", (128, 64)),
}


def load_sprites(assets_dir: Path | None, *, disabled: bool = False) -> dict:
    """Load all sprites from `assets_dir / 'sprites'`. Returns a dict
    mapping sprite name -> pygame.Surface. Missing files log a notice
    and are absent from the result.

    If `disabled` is True, returns an empty dict (forces full procedural
    fallback). If `assets_dir` is None or doesn't exist, also returns {}.
    """
    if disabled or assets_dir is None:
        return {}
    sprites_dir = assets_dir / "sprites"
    if not sprites_dir.exists() or not sprites_dir.is_dir():
        return {}

    import pygame
    out: dict = {}
    for name, (filename, _hint) in SPRITE_MANIFEST.items():
        path = sprites_dir / filename
        if not path.exists():
            logger.info(
                "sprite %s not present at %s; using procedural fallback",
                name, path,
            )
            continue
        try:
            surf = pygame.image.load(str(path)).convert_alpha()
        except Exception as e:
            logger.warning(
                "failed to load sprite %s: %s; using procedural fallback",
                name, e,
            )
            continue
        out[name] = surf
    return out


def loaded_names(sprites: dict) -> set[str]:
    """Return the set of sprite names that loaded successfully."""
    return set(sprites.keys())
