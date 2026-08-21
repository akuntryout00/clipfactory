"""AI Lab providers: keyframe planner (LLM), image generation (OpenAI), video interpolation (Google). Fakes for tests."""
from __future__ import annotations

import base64
import logging
import subprocess
import time
from pathlib import Path
from typing import Protocol

from app.config.settings import get_settings
from app.lab.schemas import KeyframePlan, KeyframeSpec

log = logging.getLogger(__name__)
W, H = 1080, 1920


# ---------------- planner ----------------

class Planner(Protocol):
    def plan(self, *, prompt: str, n_keyframes: int, segment_seconds: int, style: str | None) -> KeyframePlan: ...


PLAN_SYSTEM = (
    "You are a storyboard artist for vertical (9:16) AI-generated TikTok videos. Given a user idea, write N keyframes that a "
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
        user = (f"IDEA: {prompt}\nSTYLE PREFERENCE: {style or 'cinematic, realistic'}\n"
                f"Write exactly {n_keyframes} keyframes (index 0..{n_keyframes - 1}); each segment between neighbours lasts {segment_seconds} seconds.")
        kwargs = dict(model=self.model, messages=[{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": user}], response_format=KeyframePlan)
        if not self.model.startswith(("o1", "o3", "o4", "gpt-5")):
            kwargs["temperature"] = 0.7
        msg = self._client.chat.completions.parse(**kwargs).choices[0].message
        if msg.parsed is None:
            raise RuntimeError(msg.refusal or "planner returned nothing")
        plan = msg.parsed
        # enforce count/index
        plan.keyframes = [KeyframeSpec(index=i, prompt=k.prompt, caption=k.caption, motion_to_next=k.motion_to_next)
                          for i, k in enumerate(plan.keyframes[:n_keyframes])]
        while len(plan.keyframes) < n_keyframes:
            last = plan.keyframes[-1]
            plan.keyframes.append(KeyframeSpec(index=len(plan.keyframes), prompt=last.prompt, caption=last.caption))
        return plan


class FakePlanner:
    name = "fake"

    def plan(self, *, prompt: str, n_keyframes: int, segment_seconds: int, style: str | None) -> KeyframePlan:
        return KeyframePlan(style_guide=f"fake style for: {prompt[:40]}",
                            keyframes=[KeyframeSpec(index=i, prompt=f"{prompt} — keyframe {i}, vertical 9:16", caption=f"Frame {i}", motion_to_next="slow push in")
                                       for i in range(n_keyframes)])


# ---------------- images ----------------

class ImageGen(Protocol):
    name: str
    model: str

    def generate(self, *, prompt: str, out_path: Path, reference: Path | None = None) -> Path:
        """Generate one 9:16 keyframe. `reference` = the previous keyframe image (same character/style continuity)."""
        ...


def _to_916_png(src: Path, dst: Path) -> Path:
    """Crop to 9:16 (centre) and scale to 1080×1920 PNG."""
    vf = "crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale=1080:1920:flags=lanczos"
    subprocess.run([get_settings().ffmpeg_bin, "-y", "-loglevel", "error", "-i", str(src), "-vf", vf, "-frames:v", "1", str(dst)], check=True)
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

    def generate(self, *, prompt: str, out_path: Path, reference: Path | None = None) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        s = get_settings()
        if reference is not None and reference.is_file() and not self.model.startswith("dall-e"):
            # continuity: edit endpoint with the previous keyframe as the reference image
            edit_prompt = ("Use the reference image for continuity: keep the SAME character (face, hair, wardrobe), the same place, "
                           "palette, lens and rendering style. Now create the NEXT frame of the story:\n" + prompt)
            extra = {"input_fidelity": s.openai_image_input_fidelity} if self.model == "gpt-image-1" else {}  # gpt-image-2 rejects it
            with reference.open("rb") as fh:
                resp = self._client.images.edit(model=self.model, image=[fh], prompt=edit_prompt, n=1, size=self.size,
                                                quality=s.openai_image_quality, **extra)
        else:
            kwargs = dict(model=self.model, prompt=prompt, n=1, size=self.size)
            if not self.model.startswith("dall-e"):
                kwargs.update(quality=s.openai_image_quality, output_format="png")
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

    def generate(self, *, prompt: str, out_path: Path, reference: Path | None = None) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        color = self._colors[sum(map(ord, prompt)) % len(self._colors)]
        subprocess.run([get_settings().ffmpeg_bin, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s={W}x{H}:d=0.1",
                        "-frames:v", "1", str(out_path)], check=True)
        return out_path


# ---------------- video ----------------

class VideoGen(Protocol):
    name: str
    model: str
    max_seconds: int  # longest clip this provider makes in one call
    last_ref: str | None  # provider reference of the last generated clip (Omni interaction id), for conversational edits

    def animate(self, *, first: Path, last: Path, prompt: str, seconds: int, out_path: Path) -> Path: ...

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

    def animate(self, *, first: Path, last: Path, prompt: str, seconds: int, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        b64 = lambda p: base64.b64encode(p.read_bytes()).decode()  # noqa: E731
        it = self._client.interactions.create(
            model=self.model,
            input=[{"type": "image", "data": b64(first), "mime_type": "image/png"},
                   {"type": "image", "data": b64(last), "mime_type": "image/png"},
                   {"type": "text", "text": prompt}],
            response_format={"type": "video", "aspect_ratio": "9:16", "delivery": "uri"},
            background=False, store=True,
        )
        self.last_ref = getattr(it, "id", None)
        return self._save_interaction_video(it, out_path)

    def edit(self, *, ref: str, instruction: str, out_path: Path) -> Path:
        """Stateful edit: new interaction chained to the previous one (official 'Stateful video editing')."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        it = self._client.interactions.create(
            model=self.model, previous_interaction_id=ref, input=instruction,
            response_format={"type": "video", "aspect_ratio": "9:16", "delivery": "uri"}, background=False, store=True,
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

    def animate(self, *, first: Path, last: Path, prompt: str, seconds: int, out_path: Path) -> Path:
        from google.genai import types

        out_path.parent.mkdir(parents=True, exist_ok=True)
        first_img = types.Image(image_bytes=first.read_bytes(), mime_type="image/png")
        cfg = types.GenerateVideosConfig(aspect_ratio="9:16", duration_seconds=seconds, number_of_videos=1,
                                         person_generation=get_settings().google_person_generation,
                                         last_frame=types.Image(image_bytes=last.read_bytes(), mime_type="image/png"))
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

            data = httpx.get(vid.uri, headers={"x-goog-api-key": get_settings().google_api_key or ""}, timeout=300, follow_redirects=True).content
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
    subprocess.run([get_settings().ffmpeg_bin, "-y", "-loglevel", "error", "-i", str(src), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "18", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-video_track_timescale", "15360", str(dst)], check=True)


class FakeVideoGen:
    """Cross-fades first→last image over the requested seconds (with a subtle zoom) — offline stand-in."""

    name = "fake"
    model = "fake-video"
    max_seconds = 8
    last_ref: str | None = None
    _counter = 0

    def edit(self, *, ref: str, instruction: str, out_path: Path) -> Path:
        """Pretend-edit: re-encode the existing clip with a tint so the file changes."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        src = out_path if out_path.is_file() else None
        if src is None:
            raise RuntimeError("nothing to edit")
        tmp = out_path.with_suffix(".edit.mp4")
        subprocess.run([get_settings().ffmpeg_bin, "-y", "-loglevel", "error", "-i", str(src), "-vf", "hue=s=0.3", "-c:v", "libx264", "-preset", "ultrafast",
                        "-crf", "28", "-c:a", "copy", str(tmp)], check=True)
        tmp.replace(out_path)
        FakeVideoGen._counter += 1
        self.last_ref = f"fake_interaction_{FakeVideoGen._counter}"
        return out_path

    def animate(self, *, first: Path, last: Path, prompt: str, seconds: int, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        FakeVideoGen._counter += 1
        self.last_ref = f"fake_interaction_{FakeVideoGen._counter}"
        d = max(2, seconds)
        fc = (f"[0:v]scale={W}:{H},format=yuv420p,loop=loop={d*30}:size=1:start=0,setpts=N/30/TB[a];"
              f"[1:v]scale={W}:{H},format=yuv420p,loop=loop={d*30}:size=1:start=0,setpts=N/30/TB[b];"
              f"[a][b]xfade=transition=fade:duration={d - 1}:offset=0.5,fps=30[v];"
              f"anullsrc=r=44100:cl=stereo,atrim=0:{d}[aout]")
        subprocess.run([get_settings().ffmpeg_bin, "-y", "-loglevel", "error", "-i", str(first), "-i", str(last), "-filter_complex", fc,
                        "-map", "[v]", "-map", "[aout]", "-t", str(d), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                        "-c:a", "aac", "-video_track_timescale", "15360", str(out_path)], check=True)
        return out_path


# ---------------- factories ----------------

def get_planner(name: str | None = None) -> Planner:
    n = (name or get_settings().lab_planner).lower()
    return FakePlanner() if n == "fake" else OpenAIPlanner()


def get_image_gen(name: str | None = None) -> ImageGen:
    n = (name or get_settings().lab_image_provider).lower()
    return FakeImageGen() if n == "fake" else OpenAIImageGen()


def get_video_gen(name: str | None = None) -> VideoGen:
    n = (name or get_settings().lab_video_provider).lower()
    if n == "fake":
        return FakeVideoGen()
    if n in ("veo", "google"):
        return GoogleVideoGen()
    return OmniVideoGen()
