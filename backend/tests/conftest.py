import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
import app.models  # noqa: F401  (register tables on Base)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def make_clip(path: Path, seconds: float = 3.0, size: str = "360x640", fps: int = 30, color: str = "blue") -> Path:
    """Create a tiny synthetic vertical clip with ffmpeg (lavfi) for tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s={size}:r={fps}:d={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture()
def mini_assets(tmp_path: Path) -> Path:
    """A tiny asset library: 3 categories, 6 clips + seed json."""
    root = tmp_path / "assets"
    clips = {
        "desk/typing_01.mp4": ("typing", ["typing", "laptop", "desk", "work"], "close", 9.0),
        "desk/coffee_pour_01.mp4": ("pouring_coffee", ["coffee", "cup", "cafe", "desk"], "close", 6.0),
        "phone/phone_scroll_01.mp4": ("scrolling_phone", ["phone", "scrolling", "social"], "close", 10.0),
        "phone/phone_call_01.mp4": ("phone_call", ["phone", "call", "talking"], "medium", 5.0),
        "walking/street_walk_01.mp4": ("walking", ["walking", "street", "city", "commute"], "wide", 12.0),
        "reaction/stressed_01.mp4": ("stressed", ["stressed", "frustrated", "reaction", "face"], "close", 4.0),
    }
    seed = []
    colors = ["blue", "red", "green", "orange", "purple", "gray"]
    for i, (rel, (action, tags, shot, dur)) in enumerate(clips.items(), start=1):
        make_clip(root / rel, seconds=dur, color=colors[(i - 1) % len(colors)])
        seed.append({
            "id": f"asset_{i:03d}",
            "file": rel,
            "description": f"{action.replace('_', ' ')} clip",
            "tags": tags,
            "shot": shot,
            "duration": dur,
        })
    (root / "_rejected").mkdir()
    make_clip(root / "_rejected" / "bad.mp4")
    (root / "_originals").mkdir()
    import json
    (root / "broll_database.json").write_text(json.dumps(seed))
    return root
