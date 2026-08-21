"""Duration → segment plan. Each segment is one AI-animated clip between two keyframes (4–8 s)."""
from __future__ import annotations

import math

MIN_SEG, MAX_SEG = 4, 8


def segment_plan(target_duration: float, max_seg: int = MAX_SEG) -> tuple[int, int]:
    """Return (n_segments, seconds_per_segment) covering the target with the fewest clips of ≤ max_seg seconds."""
    max_seg = max(MIN_SEG, int(max_seg))
    n = max(2, math.ceil(target_duration / max_seg))
    seg = int(round(target_duration / n))
    seg = max(MIN_SEG, min(max_seg, seg))
    return n, seg
