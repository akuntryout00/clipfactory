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


class ShotSpec(BaseModel):
    """One shot = one AI-animated clip between a start frame and an end frame, decided by the story, not by a fixed grid."""

    index: int
    title: str = Field(description="3-6 word label, e.g. 'Arrives at the lake'")
    seconds: int = Field(description="clip length in seconds, within the allowed range; short for beats, long for slow moves")
    transition: str = Field(description="'cut' = hard cut (new start frame) | 'continuous' = continues from the previous shot's end frame")
    start_prompt: str = Field(
        description="detailed image prompt for the FIRST frame (ignored when continuous — the previous end frame is reused)"
    )
    end_prompt: str = Field(description="detailed image prompt for the LAST frame of this shot")
    motion: str = Field(description="camera + subject motion between the two frames, incl. pacing (slow push, whip pan, static…)")


class ShotPlan(BaseModel):
    style_guide: str = Field(description="Consistent look for ALL frames: characters, wardrobe, palette, lens, lighting, rendering style")
    shots: list[ShotSpec]
