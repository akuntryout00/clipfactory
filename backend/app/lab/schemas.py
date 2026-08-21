from __future__ import annotations

from pydantic import BaseModel, Field


class KeyframeSpec(BaseModel):
    index: int
    prompt: str = Field(
        description="Detailed image prompt for this keyframe (subject, action, setting, light, camera, style). Vertical 9:16."
    )
    caption: str = Field(description="3-6 word label shown to the user")
    motion_to_next: str | None = Field(
        default=None, description="What should happen between this frame and the next one (camera + subject motion)"
    )


class KeyframePlan(BaseModel):
    style_guide: str = Field(
        description="Consistent look for ALL frames: character description, wardrobe, palette, lens, lighting, rendering style"
    )
    keyframes: list[KeyframeSpec]
