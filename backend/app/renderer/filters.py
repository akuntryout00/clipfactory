"""FFmpeg filter-graph builders (visual variation: cover-scale, crop jitter, subtle zoom, fps)."""
from __future__ import annotations

import random
from dataclasses import dataclass

OUT_W, OUT_H, OUT_FPS = 1080, 1920, 30


@dataclass
class SceneLook:
    zoom: float          # total zoom over the shot, e.g. 0.04 → 100 % → 104 %
    zoom_dir: int        # +1 zoom in, -1 zoom out, 0 static
    oversample: float    # 1.0..1.08 — scale slightly bigger than frame to allow crop jitter
    jitter_x: float      # 0..1 — position of crop window horizontally
    jitter_y: float      # 0..1


def pick_look(rng: random.Random, scene_index: int) -> SceneLook:
    """Alternate zoom direction so consecutive shots don't feel identical; keep magnitudes subtle (PRD §19)."""
    zoom = rng.uniform(0.025, 0.05)
    zoom_dir = rng.choice([1, 1, -1, 0]) if scene_index else 1
    return SceneLook(zoom=round(zoom, 3), zoom_dir=zoom_dir, oversample=round(rng.uniform(1.0, 1.06), 3),
                     jitter_x=rng.random(), jitter_y=rng.random())


def scene_vf(look: SceneLook, duration: float, w: int = OUT_W, h: int = OUT_H, fps: int = OUT_FPS) -> str:
    """Build the -vf chain for one scene clip.

    1. scale to cover (w*oversample, h*oversample) keeping aspect
    2. crop w×h at a jittered position (dynamic crop)
    3. subtle continuous zoom via time-evaluated scale + centre crop
    4. fps + pixel format
    """
    ow, oh = int(w * look.oversample) // 2 * 2, int(h * look.oversample) // 2 * 2
    cover = f"scale={ow}:{oh}:force_original_aspect_ratio=increase"
    x = f"(iw-{w})*{look.jitter_x:.3f}"
    y = f"(ih-{h})*{look.jitter_y:.3f}"
    crop_jitter = f"crop={w}:{h}:{x}:{y}"
    d = max(duration, 0.1)
    if look.zoom_dir == 0 or look.zoom <= 0:
        zoom_chain = ""
    else:
        z = look.zoom
        # zoom in: factor 1 → 1+z ; zoom out: 1+z → 1
        factor = f"(1+{z}*t/{d:.3f})" if look.zoom_dir > 0 else f"(1+{z}-{z}*t/{d:.3f})"
        zoom_chain = (f",scale=w='trunc({w}*{factor}/2)*2':h='trunc({h}*{factor}/2)*2':eval=frame"
                      f",crop={w}:{h}")
    return f"{cover},{crop_jitter}{zoom_chain},fps={fps},setsar=1,format=yuv420p"
