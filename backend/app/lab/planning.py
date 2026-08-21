"""Duration → segment plan. Each segment is one AI-animated clip between two keyframes."""

from __future__ import annotations

import math

MIN_SEG, MAX_SEG = 4, 8
PREFERRED_MAX_SEG = 10  # storyboard granularity: never plan clips longer than this even if the model allows more


def segment_plan(target_duration: float, max_seg: int = MAX_SEG, min_seg: int = MIN_SEG) -> tuple[int, int]:
    """Return (n_segments, seconds_per_segment).

    - clips are capped at min(max_seg, PREFERRED_MAX_SEG) seconds and never shorter than the provider's min_seg
    - very short videos (>= 3 s) become a single clip (2 keyframes); the clip may be stretched to min_seg
    """
    cap = max(1, min(int(max_seg), PREFERRED_MAX_SEG))
    min_seg = max(1, int(min_seg))
    n = max(1, math.ceil(target_duration / cap))
    seg = int(round(target_duration / n))
    seg = max(min_seg, min(cap, seg))
    return n, seg
