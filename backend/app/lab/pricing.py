"""Rough cost estimates for the AI Lab (shown in the UI before generating). Numbers are list prices, not invoices."""
from __future__ import annotations

from app.config.settings import get_settings
from app.lab.planning import segment_plan
from app.lab.providers import provider_meta

# OpenAI image generation list prices per 1024x1536 image (approx., by quality)
IMAGE_PRICE_BY_QUALITY = {"low": 0.02, "medium": 0.07, "high": 0.19}
PLANNER_COST = 0.02  # one storyboard call


def estimate_cost(provider_id: str, target_duration: float) -> dict:
    meta = provider_meta(provider_id)  # raises ValueError for unknown provider
    n, seg = segment_plan(target_duration, max_seg=meta["max_seconds"], min_seg=meta["min_seconds"])
    video_seconds = n * seg
    video_cost = round(video_seconds * float(meta["price_per_second"]), 2)
    s = get_settings()
    per_image = IMAGE_PRICE_BY_QUALITY.get((s.openai_image_quality or "low").lower(), 0.05)
    keyframes = n + 1
    image_cost = round(keyframes * per_image, 2)
    return {
        "provider": provider_id, "label": meta["label"], "target_duration": target_duration,
        "n_segments": n, "segment_seconds": seg, "video_seconds": video_seconds, "keyframes": keyframes,
        "price_per_second": meta["price_per_second"], "video_cost": video_cost,
        "image_cost": image_cost, "per_image": per_image, "image_quality": s.openai_image_quality,
        "planner_cost": PLANNER_COST, "total": round(video_cost + image_cost + PLANNER_COST, 2),
        "note": "list prices (fal/Google/OpenAI), excludes retries and re-dos",
    }
