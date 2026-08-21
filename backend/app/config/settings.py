"""Application settings (12-factor, .env driven)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # providers
    llm_provider: str = Field(default="openai", description="openai | fake")
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1"
    voice_provider: str = Field(default="elevenlabs", description="elevenlabs | fake")
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None

    # AI Lab (isolated module): OpenAI images + Google video
    openai_image_model: str = "gpt-image-2"
    openai_image_size: str = "1024x1536"
    openai_image_quality: str = "high"
    google_api_key: str | None = None
    google_video_model: str = "veo-3.1-fast-generate-preview"
    google_person_generation: str = "allow_adult"  # Veo filters people from image inputs otherwise
    lab_planner: str = "openai"          # openai | fake
    lab_image_provider: str = "openai"   # openai | fake
    lab_video_provider: str = "google"   # google | fake

    # storage
    database_url: str = f"sqlite:///{REPO_DIR / 'storage' / 'ttcf.db'}"
    storage_dir: Path = REPO_DIR / "storage"
    assets_dir: Path = REPO_DIR / "assets"
    configs_dir: Path = REPO_DIR / "configs"

    # rendering
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    font_file: str | None = None  # override caption font file path
    render_threads: int = 0  # 0 = ffmpeg default

    # misc
    default_persona: str = "michael"
    log_level: str = "INFO"

    @property
    def voices_dir(self) -> Path:
        return self.storage_dir / "voices"

    @property
    def renders_dir(self) -> Path:
        return self.storage_dir / "renders"

    @property
    def projects_dir(self) -> Path:
        return self.storage_dir / "projects"

    @property
    def temp_dir(self) -> Path:
        return self.storage_dir / "temp"

    @property
    def music_dir(self) -> Path:
        return self.storage_dir / "music"

    def ensure_dirs(self) -> None:
        for d in (self.voices_dir, self.renders_dir, self.projects_dir, self.temp_dir, self.music_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
