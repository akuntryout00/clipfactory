"""AI Lab providers: keyframe planner (LLM), image generation (OpenAI), video interpolation (Google). Fakes for tests."""

from __future__ import annotations

import base64
import logging
import subprocess
import time
from pathlib import Path
from typing import Protocol

from app.config.settings import get_settings
from app.lab.schemas import KeyframePlan, KeyframeSpec, ShotPlan, ShotSpec

log = logging.getLogger(__name__)
W, H = 1080, 1920


# ---------------- planner ----------------


class Planner(Protocol):
    def plan(self, *, prompt: str, n_keyframes: int, segment_seconds: int, style: str | None) -> KeyframePlan: ...

    def plan_shots(self, *, prompt: str, target_seconds: float, min_clip: int, max_clip: int, style: str | None) -> ShotPlan: ...


SHOTS_SYSTEM = (
    "You are a director + storyboard artist for vertical (9:16) AI-generated short videos. The video is built from SHOTS: each shot "
    "is one clip a video model animates from a START frame to an END frame. YOU decide the shots from the story — how many, how "
    "long each, and where the camera cuts — not a fixed grid.\n"
    "Rules:\n"
    "- Break the idea into beats; give each beat a shot with its own length (quick beats 3-5 s, slow reveals or time-lapses longer), "
    "all within the allowed clip range; the lengths must add up to the target (±1 s per shot is fine).\n"
    "- transition='cut' starts a new composition (new start frame); 'continuous' keeps the camera rolling from the previous shot's "
    "end frame (the start_prompt is then ignored). Use cuts for new angles/places, continuous for an unbroken move.\n"
    "- Start/end frames of a shot must be plausible to interpolate in its seconds: same place and characters, a clear but modest "
    "change (push-in, subject moves, light shifts). Describe subject, action/pose, setting, light, lens, angle; repeat identity "
    "details; say 'vertical 9:16 composition'. No text, logos, split screens.\n"
    "- First write a style_guide that keeps characters, wardrobe, palette, lens and rendering consistent across ALL frames.\n"
    "Output JSON only."
)


def _normalise_shots(plan: ShotPlan, target: float, min_clip: int, max_clip: int) -> ShotPlan:
    shots = plan.shots[:12] or []
    if not shots:
        raise RuntimeError("planner returned no shots")
    for i, sh in enumerate(shots):
        sh.index = i
        sh.seconds = max(min_clip, min(max_clip, int(round(sh.seconds or min_clip))))
        sh.transition = "continuous" if (i > 0 and str(sh.transition).lower().startswith("cont")) else "cut"
    total = sum(sh.seconds for sh in shots)
    if total and abs(total - target) > max(2, 0.2 * target):  # rescale only when clearly off target
        scale = target / total
        for sh in shots:
            sh.seconds = max(min_clip, min(max_clip, int(round(sh.seconds * scale))))
    plan.shots = shots
    return plan


PLAN_SYSTEM = (
    "You are a storyboard artist for vertical (9:16) AI-generated short-form videos. Given a user idea, write N keyframes that a "
    "video model will animate BETWEEN (first→last frame interpolation per segment). Rules:\n"
    "- First define a style_guide that keeps the same character(s), wardrobe, palette, lens and rendering style across ALL frames.\n"
    "- Each keyframe prompt must be self-contained and detailed (subject, action/pose, setting, light, camera angle, mood) and "
    "repeat the key identity details so images stay consistent. Mention 'vertical 9:16 composition'.\n"
    "- Consecutive keyframes must be plausible to interpolate in the given seconds: same location/character, a clear but modest "
    "change (camera push, subject moves, light shifts). No text, no logos, no split screens.\n"
    "- motion_to_next describes the camera and subject motion for the segment after that frame.\n"
    "Output JSON only."
)


class OpenAIPlanner:
    name = "openai"

    def __init__(self):
        from openai import OpenAI

        s = get_settings()
        if not s.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self._client = OpenAI(api_key=s.openai_api_key)
        self.model = s.openai_model

    def plan(self, *, prompt: str, n_keyframes: int, segment_seconds: int, style: str | None) -> KeyframePlan:
        user = (
            f"IDEA: {prompt}\nSTYLE PREFERENCE: {style or 'cinematic, realistic'}\n"
            f"Write exactly {n_keyframes} keyframes (index 0..{n_keyframes - 1}); each segment between neighbours lasts {segment_seconds} seconds."
        )
        kwargs = dict(
            model=self.model,
            messages=[{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": user}],
            response_format=KeyframePlan,
        )
        if not self.model.startswith(("o1", "o3", "o4", "gpt-5")):
            kwargs["temperature"] = 0.7
        msg = self._client.chat.completions.parse(**kwargs).choices[0].message
        if msg.parsed is None:
            raise RuntimeError(msg.refusal or "planner returned nothing")
        plan = msg.parsed
        # enforce count/index
        plan.keyframes = [
            KeyframeSpec(index=i, prompt=k.prompt, caption=k.caption, motion_to_next=k.motion_to_next)
            for i, k in enumerate(plan.keyframes[:n_keyframes])
        ]
        while len(plan.keyframes) < n_keyframes:
            last = plan.keyframes[-1]
            plan.keyframes.append(KeyframeSpec(index=len(plan.keyframes), prompt=last.prompt, caption=last.caption))
        return plan

    def plan_shots(self, *, prompt: str, target_seconds: float, min_clip: int, max_clip: int, style: str | None) -> ShotPlan:
        user = (
            f"IDEA: {prompt}\nSTYLE PREFERENCE: {style or 'cinematic, realistic'}\n"
            f"TARGET LENGTH: {target_seconds:.0f} seconds total. Each shot must be {min_clip}-{max_clip} seconds. "
            "Decide the number of shots from the story (typically 2-6)."
        )
        kwargs = dict(
            model=self.model,
            messages=[{"role": "system", "content": SHOTS_SYSTEM}, {"role": "user", "content": user}],
            response_format=ShotPlan,
        )
        if not self.model.startswith(("o1", "o3", "o4", "gpt-5")):
            kwargs["temperature"] = 0.7
        msg = self._client.chat.completions.parse(**kwargs).choices[0].message
        if msg.parsed is None:
            raise RuntimeError(msg.refusal or "planner returned nothing")
        return _normalise_shots(msg.parsed, target_seconds, min_clip, max_clip)


class FakePlanner:
    name = "fake"

    def plan_shots(self, *, prompt: str, target_seconds: float, min_clip: int, max_clip: int, style: str | None) -> ShotPlan:
        from app.lab.planning import segment_plan

        n, seg = segment_plan(target_seconds, max_seg=max_clip, min_seg=min_clip)
        shots = [
            ShotSpec(
                index=i,
                title=f"Beat {i + 1}",
                seconds=seg,
                transition="cut" if i % 2 == 0 else "continuous",
                start_prompt=f"{prompt} — shot {i + 1} start, vertical 9:16",
                end_prompt=f"{prompt} — shot {i + 1} end, vertical 9:16",
                motion="slow push-in" if i % 2 == 0 else "gentle pan",
            )
            for i in range(n)
        ]
        return _normalise_shots(ShotPlan(style_guide=f"fake style for: {prompt[:40]}", shots=shots), target_seconds, min_clip, max_clip)

    def plan(self, *, prompt: str, n_keyframes: int, segment_seconds: int, style: str | None) -> KeyframePlan:
        return KeyframePlan(
            style_guide=f"fake style for: {prompt[:40]}",
            keyframes=[
                KeyframeSpec(index=i, prompt=f"{prompt} — keyframe {i}, vertical 9:16", caption=f"Frame {i}", motion_to_next="slow push in")
                for i in range(n_keyframes)
            ],
        )


# ---------------- images ----------------


class ImageModerationError(RuntimeError):
    """The image provider refused the request (safety system) — callers may try another engine."""


def identity_prompts(scene: str) -> list[str]:
    """Prompts that place the person from the reference photo into a new scene, strongest first.

    Wording matters: asking to "recreate this real person / exact identity" trips OpenAI's safety system for photos of real
    people, while "the person from the reference image" with a described scene passes. We keep the face/hair/build, and
    describe a NEW composition — the photo is a character reference, not the start frame.
    """
    return [
        (
            "Create a new photorealistic image of the scene described below, featuring the person from the reference image as the "
            "subject. Keep their face, hairstyle, facial hair, skin tone, glasses and build as in the photo so they are clearly the "
            "same person; sharp, detailed face, natural skin texture. Do not copy the photo's background or framing — build the "
            "scene fresh. Vertical 9:16 video still, natural light, candid documentary look, no text, no watermark.\nScene: " + scene
        ),
        (
            "Put the person from the reference image into this scene, keeping their face and hair as in the photo. "
            "Vertical 9:16 photo, realistic, natural light, no text.\nScene: " + scene
        ),
    ]


class ImageGen(Protocol):
    name: str
    model: str

    def generate(
        self, *, prompt: str, out_path: Path, reference: Path | None = None, identity: bool = False, quality: str | None = None
    ) -> Path:
        """Generate one 9:16 keyframe. `reference` = previous keyframe (continuity) or, with identity=True, a real person's photo."""
        ...


def _to_916_png(src: Path, dst: Path) -> Path:
    """Crop to 9:16 (centre) and scale to 1080×1920 PNG."""
    vf = "crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale=1080:1920:flags=lanczos"
    subprocess.run(
        [get_settings().ffmpeg_bin, "-y", "-loglevel", "error", "-i", str(src), "-vf", vf, "-frames:v", "1", str(dst)], check=True
    )
    return dst


class OpenAIImageGen:
    name = "openai"

    def __init__(self):
        from openai import OpenAI

        s = get_settings()
        if not s.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self._client = OpenAI(api_key=s.openai_api_key)
        self.model = s.openai_image_model
        self.size = s.openai_image_size

    def generate(
        self,
        *,
        prompt: str,
        out_path: Path,
        reference: Path | None = None,
        identity: bool = False,
        quality: str | None = None,
    ) -> Path:
        """reference = previous keyframe (continuity) or, with identity=True, a photo of a real person whose face must be kept."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        s = get_settings()
        q = quality or s.openai_image_quality
        if reference is not None and reference.is_file() and not self.model.startswith("dall-e"):
            extra = {"input_fidelity": "high" if identity else s.openai_image_input_fidelity} if self.model == "gpt-image-1" else {}
            variants = (
                identity_prompts(prompt)
                if identity
                else [
                    "Use the reference image for continuity: keep the SAME character (face, hair, wardrobe), the same place, "
                    "palette, lens and rendering style. Now create the NEXT frame of the story:\n" + prompt
                ]
            )
            resp = None
            last_err: Exception | None = None
            for edit_prompt in variants:
                try:
                    with reference.open("rb") as fh:
                        resp = self._client.images.edit(
                            model=self.model, image=[fh], prompt=edit_prompt, n=1, size=self.size, quality=q, **extra
                        )
                    break
                except Exception as exc:  # noqa: BLE001
                    last_err = exc
                    if "moderation" not in str(exc).lower():
                        raise
            if resp is None:
                raise ImageModerationError(f"image provider refused the reference photo: {str(last_err)[:200]}")
        else:
            kwargs = dict(model=self.model, prompt=prompt, n=1, size=self.size)
            if not self.model.startswith("dall-e"):
                kwargs.update(quality=q, output_format="png")
            resp = self._client.images.generate(**kwargs)
        data = resp.data[0]
        raw = out_path.with_suffix(".raw.png")
        if getattr(data, "b64_json", None):
            raw.write_bytes(base64.b64decode(data.b64_json))
        elif getattr(data, "url", None):
            import httpx

            raw.write_bytes(httpx.get(data.url, timeout=120).content)
        else:
            raise RuntimeError("image API returned no image")
        _to_916_png(raw, out_path)
        raw.unlink(missing_ok=True)
        return out_path


class FakeImageGen:
    name = "fake"
    model = "fake-image"
    _colors = ["0x3b82f6", "0xf59e0b", "0x10b981", "0xef4444", "0x8b5cf6", "0x14b8a6"]

    def generate(
        self,
        *,
        prompt: str,
        out_path: Path,
        reference: Path | None = None,
        identity: bool = False,
        quality: str | None = None,
    ) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        color = self._colors[sum(map(ord, prompt)) % len(self._colors)]
        subprocess.run(
            [
                get_settings().ffmpeg_bin,
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s={W}x{H}:d=0.1",
                "-frames:v",
                "1",
                str(out_path),
            ],
            check=True,
        )
        return out_path


# ---------------- video ----------------


class VideoGen(Protocol):
    name: str
    model: str
    max_seconds: int  # longest clip this provider makes in one call
    last_ref: str | None  # provider reference of the last generated clip (Omni interaction id), for conversational edits

    def animate(self, *, first: Path, last: Path | None, prompt: str, seconds: int, out_path: Path) -> Path: ...

    def edit(self, *, ref: str, instruction: str, out_path: Path) -> Path:
        """Conversational edit of a previously generated clip (raise NotImplementedError if unsupported)."""
        ...


class OmniVideoGen:
    """Gemini Omni Flash via the Interactions API (official docs: ai.google.dev/gemini-api/docs/omni).

    Omni does NOT support first/last-frame interpolation, so we use its tag syntax: the first keyframe is the
    literal <FIRST_FRAME>, the next keyframe is an <IMAGE_REF_0> reference describing how the shot should end,
    and the prompt asks for one continuous shot of N seconds (Omni generates up to ~10 s per call).
    """

    name = "omni"
    max_seconds = 10
    min_seconds = 2

    def __init__(self):
        from google import genai

        s = get_settings()
        if not s.google_api_key:
            raise RuntimeError("GOOGLE_API_KEY is not set")
        self._client = genai.Client(api_key=s.google_api_key)
        self.model = s.google_video_model  # gemini-omni-flash-preview
        self.last_ref: str | None = None

    @staticmethod
    def build_prompt(motion: str, seconds: int, style: str) -> str:
        return (
            "[# Sources <FIRST_FRAME>@Image1] [# References <IMAGE_REF_0>@Image2] "
            f"A single continuous unbroken shot of {seconds} seconds, no scene cuts. Start exactly on Image1. "
            f"{motion.strip().rstrip('.')}. By the end of the shot the scene looks like Image2 (same subject, place and framing as Image2). "
            f"{style.strip()} Keep the same character, wardrobe, location and color grade throughout. "
            "Natural ambient sound only, no dialogue, no music, no on-screen text. "
            "Use Image1 as the starting frame. Use Image2 as a reference for the end of the shot, not as a literal frame."
        )

    def animate(self, *, first: Path, last: Path | None, prompt: str, seconds: int, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        b64 = lambda p: base64.b64encode(p.read_bytes()).decode()  # noqa: E731
        images = [{"type": "image", "data": b64(first), "mime_type": "image/png"}]
        if last is not None:
            images.append({"type": "image", "data": b64(last), "mime_type": "image/png"})
        it = self._client.interactions.create(
            model=self.model,
            input=[*images, {"type": "text", "text": prompt}],
            response_format={"type": "video", "aspect_ratio": "9:16", "delivery": "uri"},
            background=False,
            store=True,
        )
        self.last_ref = getattr(it, "id", None)
        return self._save_interaction_video(it, out_path)

    def edit(self, *, ref: str, instruction: str, out_path: Path) -> Path:
        """Stateful edit: new interaction chained to the previous one (official 'Stateful video editing')."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        it = self._client.interactions.create(
            model=self.model,
            previous_interaction_id=ref,
            input=instruction,
            response_format={"type": "video", "aspect_ratio": "9:16", "delivery": "uri"},
            background=False,
            store=True,
        )
        self.last_ref = getattr(it, "id", None)
        return self._save_interaction_video(it, out_path)

    def _save_interaction_video(self, it, out_path: Path) -> Path:
        if it.status != "completed":
            raise RuntimeError(f"omni interaction {it.status}: {it.errors}")
        ov = it.output_video
        data: bytes | None = None
        if ov is not None and ov.data:
            data = base64.b64decode(ov.data)
        elif ov is not None and ov.uri:
            name = "files/" + ov.uri.split("/files/")[1].split(":")[0]
            t0 = time.time()
            while True:
                f = self._client.files.get(name=name)
                state = getattr(f.state, "name", str(f.state))
                if state == "ACTIVE":
                    break
                if state == "FAILED" or time.time() - t0 > 600:
                    raise RuntimeError(f"omni video file {state}")
                time.sleep(5)
            data = self._client.files.download(file=ov.uri)
        if not data:
            # fall back to steps (REST shape)
            for step in it.steps or []:
                for part in getattr(step, "content", None) or []:
                    if getattr(part, "type", "") == "video" and getattr(part, "data", None):
                        data = base64.b64decode(part.data)
        if not data:
            raise RuntimeError("omni returned no video")
        raw = out_path.with_suffix(".raw.mp4")
        raw.write_bytes(data)
        _normalize_segment(raw, out_path)
        raw.unlink(missing_ok=True)
        return out_path


class GoogleVideoGen:
    """Google Veo (predictLongRunning) — true first + last frame interpolation via google-genai generate_videos."""

    name = "veo"
    max_seconds = 8
    min_seconds = 4
    last_ref = None

    def edit(self, *, ref: str, instruction: str, out_path: Path) -> Path:
        raise NotImplementedError("Veo does not support conversational clip editing — use 'redo with new motion' instead")

    def __init__(self):
        from google import genai

        s = get_settings()
        if not s.google_api_key:
            raise RuntimeError("GOOGLE_API_KEY is not set")
        self._client = genai.Client(api_key=s.google_api_key)
        self.model = s.google_veo_model
        self.poll_seconds = 8
        self.timeout_seconds = 900

    def animate(self, *, first: Path, last: Path | None, prompt: str, seconds: int, out_path: Path) -> Path:
        from google.genai import types

        out_path.parent.mkdir(parents=True, exist_ok=True)
        first_img = types.Image(image_bytes=first.read_bytes(), mime_type="image/png")
        cfg_kwargs = dict(
            aspect_ratio="9:16",
            duration_seconds=seconds,
            number_of_videos=1,
            person_generation=get_settings().google_person_generation,
        )
        if last is not None:
            cfg_kwargs["last_frame"] = types.Image(image_bytes=last.read_bytes(), mime_type="image/png")
        cfg = types.GenerateVideosConfig(**cfg_kwargs)
        try:  # new SDK signature
            src = types.GenerateVideosSource(prompt=prompt, image=first_img)
            op = self._client.models.generate_videos(model=self.model, source=src, config=cfg)
        except (TypeError, AttributeError):  # older SDKs
            op = self._client.models.generate_videos(model=self.model, prompt=prompt, image=first_img, config=cfg)
        t0 = time.time()
        while not getattr(op, "done", False):
            if time.time() - t0 > self.timeout_seconds:
                raise RuntimeError(f"video generation timed out after {self.timeout_seconds}s")
            time.sleep(self.poll_seconds)
            op = self._client.operations.get(op)
        if getattr(op, "error", None):
            raise RuntimeError(f"video generation failed: {op.error}")
        videos = getattr(op.response, "generated_videos", None) or []
        if not videos:
            reasons = getattr(op.response, "rai_media_filtered_reasons", None)
            raise RuntimeError("video generation returned no video" + (f" (filtered: {reasons})" if reasons else ""))
        vid = videos[0].video
        data = getattr(vid, "video_bytes", None)
        if not data:
            self._client.files.download(file=vid)
            data = getattr(vid, "video_bytes", None)
        if not data and getattr(vid, "uri", None):
            import httpx

            data = httpx.get(
                vid.uri, headers={"x-goog-api-key": get_settings().google_api_key or ""}, timeout=300, follow_redirects=True
            ).content
        if not data:
            raise RuntimeError("could not download generated video")
        raw = out_path.with_suffix(".raw.mp4")
        raw.write_bytes(data)
        _normalize_segment(raw, out_path)
        raw.unlink(missing_ok=True)
        return out_path


def _normalize_segment(src: Path, dst: Path) -> None:
    """Re-encode any provider output to 1080×1920 / 30 fps / h264 / aac-silent-or-original so concat is lossless-safe."""
    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,format=yuv420p"
    subprocess.run(
        [
            get_settings().ffmpeg_bin,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-video_track_timescale",
            "15360",
            str(dst),
        ],
        check=True,
    )


class FakeVideoGen:
    """Cross-fades first→last image over the requested seconds (with a subtle zoom) — offline stand-in."""

    name = "fake"
    model = "fake-video"
    max_seconds = 8
    min_seconds = 2
    last_ref: str | None = None
    _counter = 0

    def edit(self, *, ref: str, instruction: str, out_path: Path) -> Path:
        """Pretend-edit: re-encode the existing clip with a tint so the file changes."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        src = out_path if out_path.is_file() else None
        if src is None:
            raise RuntimeError("nothing to edit")
        tmp = out_path.with_suffix(".edit.mp4")
        subprocess.run(
            [
                get_settings().ffmpeg_bin,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(src),
                "-vf",
                "hue=s=0.3",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "28",
                "-c:a",
                "copy",
                str(tmp),
            ],
            check=True,
        )
        tmp.replace(out_path)
        FakeVideoGen._counter += 1
        self.last_ref = f"fake_interaction_{FakeVideoGen._counter}"
        return out_path

    def animate(self, *, first: Path, last: Path | None, prompt: str, seconds: int, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        last = last or first
        FakeVideoGen._counter += 1
        self.last_ref = f"fake_interaction_{FakeVideoGen._counter}"
        d = max(2, seconds)
        fc = (
            f"[0:v]scale={W}:{H},format=yuv420p,loop=loop={d * 30}:size=1:start=0,setpts=N/30/TB[a];"
            f"[1:v]scale={W}:{H},format=yuv420p,loop=loop={d * 30}:size=1:start=0,setpts=N/30/TB[b];"
            f"[a][b]xfade=transition=fade:duration={d - 1}:offset=0.5,fps=30[v];"
            f"anullsrc=r=44100:cl=stereo,atrim=0:{d}[aout]"
        )
        subprocess.run(
            [
                get_settings().ffmpeg_bin,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(first),
                "-i",
                str(last),
                "-filter_complex",
                fc,
                "-map",
                "[v]",
                "-map",
                "[aout]",
                "-t",
                str(d),
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "28",
                "-c:a",
                "aac",
                "-video_track_timescale",
                "15360",
                str(out_path),
            ],
            check=True,
        )
        return out_path


# ---------------- fal.ai (multi-model) ----------------

FAL_MODELS: dict[str, dict] = {
    "minimax-h3": {
        "endpoint": "minimax/h3/image-to-video",
        "label": "MiniMax H3 (Hailuo 3)",
        "max_seconds": 15,
        "min_seconds": 5,
        "price_hint": "~$0.26/s 2K",
        "price_per_second": 0.26,
        "note": "first+last frame, 2K, native audio · i2v arena #2",
        "args": lambda first, last, prompt, sec: {
            "prompt": prompt,
            "image_url": first,
            "end_image_url": last,
            "resolution": "2K",
            "duration": int(sec),
            "enable_prompt_expansion": False,
        },
    },
    "seedance-2.0": {
        "endpoint": "bytedance/seedance-2.0/image-to-video",
        "label": "Seedance 2.0 (720p)",
        "max_seconds": 15,
        "min_seconds": 4,
        "price_hint": "~$0.30/s",
        "price_per_second": 0.3034,
        "note": "first+last frame, audio · i2v arena #1",
        "args": lambda first, last, prompt, sec: {
            "prompt": prompt,
            "image_url": first,
            "end_image_url": last,
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "duration": str(int(sec)),
            "generate_audio": True,
        },
    },
    "seedance-2.0-fast": {
        "endpoint": "bytedance/seedance-2.0/fast/image-to-video",
        "label": "Seedance 2.0 Fast (720p)",
        "max_seconds": 15,
        "min_seconds": 4,
        "price_hint": "~$0.24/s",
        "price_per_second": 0.2419,
        "note": "cheaper/faster Seedance, first+last frame",
        "args": lambda first, last, prompt, sec: {
            "prompt": prompt,
            "image_url": first,
            "end_image_url": last,
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "duration": str(int(sec)),
            "generate_audio": True,
        },
    },
    "kling-3.0-std": {
        "endpoint": "fal-ai/kling-video/v3/standard/image-to-video",
        "label": "Kling 3.0 Standard",
        "max_seconds": 15,
        "min_seconds": 3,
        "price_hint": "~$0.08/s",
        "price_per_second": 0.084,
        "note": "cheapest; first+last frame (aspect follows the image)",
        "args": lambda first, last, prompt, sec: {
            "prompt": prompt,
            "start_image_url": first,
            "end_image_url": last,
            "duration": str(int(sec)),
            "generate_audio": False,
        },
    },
    "seedance-2.5": {
        "endpoint": "bytedance/seedance-2.5/image-to-video",
        "label": "Seedance 2.5 (720p)",
        "max_seconds": 30,
        "min_seconds": 4,
        "price_hint": "~$0.47/s",
        "price_per_second": 0.473,
        "note": "newest Seedance; single-shot up to 30 s, first+last frame, audio",
        "args": lambda first, last, prompt, sec: {
            "prompt": prompt,
            "image_url": first,
            "end_image_url": last,
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "duration": str(int(sec)),
            "generate_audio": True,
        },
    },
    "seedance-2.0-1080p": {
        "endpoint": "bytedance/seedance-2.0/image-to-video",
        "label": "Seedance 2.0 (1080p)",
        "max_seconds": 15,
        "min_seconds": 4,
        "price_hint": "~$0.68/s",
        "price_per_second": 0.682,
        "note": "same model at 1080p (sharper, 2× price)",
        "args": lambda first, last, prompt, sec: {
            "prompt": prompt,
            "image_url": first,
            "end_image_url": last,
            "aspect_ratio": "9:16",
            "resolution": "1080p",
            "duration": str(int(sec)),
            "generate_audio": True,
        },
    },
    "kling-3.0-pro": {
        "endpoint": "fal-ai/kling-video/v3/pro/image-to-video",
        "label": "Kling 3.0 Pro",
        "max_seconds": 15,
        "min_seconds": 3,
        "price_hint": "~$0.42/s",
        "price_per_second": 0.42,
        "note": "higher-quality Kling tier, first+last frame, audio",
        "args": lambda first, last, prompt, sec: {
            "prompt": prompt,
            "start_image_url": first,
            "end_image_url": last,
            "duration": str(int(sec)),
            "generate_audio": True,
        },
    },
}


def _fal():
    """Lazy import so tests can stub the client module."""
    import fal_client

    return fal_client


def _download(url: str, dst: Path) -> None:
    import httpx

    with httpx.stream("GET", url, timeout=600, follow_redirects=True) as r:
        r.raise_for_status()
        with dst.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)


def clean_args(args: dict) -> dict:
    """Drop None-valued arguments (e.g. no end frame) — fal endpoints reject explicit nulls."""
    return {k: v for k, v in args.items() if v is not None}


class FalVideoGen:
    """One provider class for every fal.ai video model in FAL_MODELS (official Seedance/MiniMax endpoints, Kling, …)."""

    name = "fal"
    last_ref = None

    def __init__(self, model_key: str | None = None):
        key = model_key or get_settings().lab_fal_model
        if key not in FAL_MODELS:
            raise ValueError(f"unknown fal model '{key}'; known: {', '.join(FAL_MODELS)}")
        self.key = key
        self.spec = FAL_MODELS[key]
        self.model = self.spec["endpoint"]
        self.max_seconds = int(self.spec["max_seconds"])
        self.min_seconds = int(self.spec.get("min_seconds", 4))
        import os

        if get_settings().fal_key and not os.environ.get("FAL_KEY"):
            os.environ["FAL_KEY"] = get_settings().fal_key  # fal_client reads FAL_KEY from the environment

    def edit(self, *, ref: str, instruction: str, out_path: Path) -> Path:
        raise NotImplementedError("fal models do not support conversational clip editing — re-animate with a new motion prompt")

    def animate(self, *, first: Path, last: Path | None, prompt: str, seconds: int, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fal = _fal()
        sec = max(self.min_seconds, min(self.max_seconds, int(seconds)))
        first_url = fal.upload_file(first)
        last_url = fal.upload_file(last) if last is not None else None
        args = clean_args(self.spec["args"](first_url, last_url, prompt, sec))
        result = fal.subscribe(self.model, arguments=args, with_logs=False)
        video = (result or {}).get("video") or {}
        url = video.get("url") if isinstance(video, dict) else None
        if not url:
            raise RuntimeError(f"fal returned no video: {str(result)[:300]}")
        raw = out_path.with_suffix(".raw.mp4")
        _download(url, raw)
        _normalize_segment(raw, out_path)
        raw.unlink(missing_ok=True)
        return out_path


class FalImageEdit:
    """fal.ai image editing with reference photos (Gemini 'nano-banana' edit) — fallback engine for face-consistent keyframes."""

    name = "fal-image"
    model = "fal-ai/nano-banana/edit"

    def generate(
        self, *, prompt: str, out_path: Path, reference: Path | None = None, identity: bool = False, quality: str | None = None
    ) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fal = _fal()
        import os

        if get_settings().fal_key and not os.environ.get("FAL_KEY"):
            os.environ["FAL_KEY"] = get_settings().fal_key
        args = {
            "prompt": identity_prompts(prompt)[0] if reference else prompt,
            "num_images": 1,
            "output_format": "png",
            "aspect_ratio": "9:16",
        }
        if reference is not None and reference.is_file():
            args["image_urls"] = [fal.upload_file(reference)]
            endpoint = self.model
        else:
            endpoint = "fal-ai/nano-banana"
        result = fal.subscribe(endpoint, arguments=args, with_logs=False)
        images = (result or {}).get("images") or []
        url = images[0].get("url") if images and isinstance(images[0], dict) else None
        if not url:
            raise RuntimeError(f"fal returned no image: {str(result)[:300]}")
        raw = out_path.with_suffix(".raw.png")
        _download(url, raw)
        _to_916_png(raw, out_path)
        raw.unlink(missing_ok=True)
        return out_path


# ---------------- factories ----------------


def get_planner(name: str | None = None) -> Planner:
    n = (name or get_settings().lab_planner).lower()
    return FakePlanner() if n == "fake" else OpenAIPlanner()


def get_image_gen(name: str | None = None) -> ImageGen:
    n = (name or get_settings().lab_image_provider).lower()
    return FakeImageGen() if n == "fake" else OpenAIImageGen()


def get_video_gen(name: str | None = None) -> VideoGen:
    """'omni' | 'veo' | 'fake' | 'fal' | 'fal:<model_key>'."""
    n = (name or get_settings().lab_video_provider).lower()
    if n == "fake" or n.startswith("fake:"):
        return FakeVideoGen()
    if n in ("veo", "google"):
        return GoogleVideoGen()
    if n == "fal" or n.startswith("fal:"):
        return FalVideoGen(n.split(":", 1)[1] if ":" in n else None)
    if n == "omni":
        return OmniVideoGen()
    raise ValueError(f"unknown video provider '{name}'")


def provider_label(provider_id: str | None) -> str:
    pid = (provider_id or get_settings().lab_video_provider).lower()
    if pid.startswith("fal:"):
        spec = FAL_MODELS.get(pid.split(":", 1)[1])
        return spec["label"] if spec else pid
    return {"omni": "Gemini Omni Flash", "veo": "Google Veo 3.1", "fake": "Fake (offline)", "fal": "fal.ai"}.get(pid, pid)


def list_video_providers() -> list[dict]:
    """Metadata for the UI: which providers/models exist, prices, limits and whether their keys are configured."""
    s = get_settings()
    rows = [
        {
            "id": "omni",
            "label": "Gemini Omni Flash",
            "vendor": "Google",
            "model": s.google_video_model,
            "max_seconds": 10,
            "min_seconds": 2,
            "supports_edit": True,
            "first_last": False,
            "audio": True,
            "price_hint": "~$0.10/s",
            "price_per_second": 0.10,
            "note": "conversational clip edits; FIRST_FRAME + end-reference (no true interpolation)",
            "available": bool(s.google_api_key),
            "needs": "GOOGLE_API_KEY",
        },
        {
            "id": "veo",
            "label": "Veo 3.1 Fast",
            "vendor": "Google",
            "model": s.google_veo_model,
            "max_seconds": 8,
            "min_seconds": 4,
            "supports_edit": False,
            "first_last": True,
            "audio": True,
            "price_hint": "~$0.15/s",
            "price_per_second": 0.15,
            "note": "true first+last frame interpolation",
            "available": bool(s.google_api_key),
            "needs": "GOOGLE_API_KEY",
        },
    ]
    for key, spec in FAL_MODELS.items():
        rows.append(
            {
                "id": f"fal:{key}",
                "label": spec["label"],
                "vendor": "fal.ai",
                "model": spec["endpoint"],
                "max_seconds": spec["max_seconds"],
                "min_seconds": spec.get("min_seconds", 4),
                "supports_edit": False,
                "first_last": True,
                "audio": spec["args"]("a", "b", "p", 5).get("generate_audio", True) is not False,
                "price_hint": spec.get("price_hint"),
                "price_per_second": float(spec.get("price_per_second", 0)),
                "note": spec.get("note"),
                "available": bool(s.fal_key),
                "needs": "FAL_KEY",
            }
        )
    rows.append(
        {
            "id": "fake",
            "label": "Fake (offline test)",
            "vendor": "local",
            "model": "fake-video",
            "max_seconds": 8,
            "min_seconds": 2,
            "supports_edit": True,
            "first_last": True,
            "audio": False,
            "price_hint": "free",
            "price_per_second": 0.0,
            "note": "cross-fade stand-in for tests",
            "available": True,
            "needs": None,
        }
    )
    return rows


def provider_meta(provider_id: str | None) -> dict:
    pid = (provider_id or get_settings().lab_video_provider).lower()
    if pid.startswith("fake:"):
        pid = "fake"
    if pid == "fal":
        pid = f"fal:{get_settings().lab_fal_model}"
    for r in list_video_providers():
        if r["id"] == pid:
            return r
    raise ValueError(f"unknown video provider '{provider_id}'")
