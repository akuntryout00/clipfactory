from pathlib import Path

import pytest
from app.config.loaders import (
    CONFIGS_DIR,
    list_templates,
    load_caption_style,
    load_persona,
    load_template,
)
from app.schemas.configs import CaptionStyleConfig, PersonaConfig, TemplateConfig


def test_persona_loads_and_validates():
    p = load_persona("young_professional")
    assert isinstance(p, PersonaConfig)
    assert p.language == "en-US"
    assert p.target_duration == 18
    assert p.max_duration == 25
    assert p.voice.provider == "elevenlabs"


def test_persona_voice_id_env_substitution(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "abc123")
    p = load_persona("young_professional")
    assert p.voice.voice_id == "abc123"


def test_all_four_templates_load():
    ids = {t.id for t in list_templates()}
    assert ids == {"story_v1", "list_v1", "pov_v1", "problem_solution_v1"}


def test_template_weights_sum_to_one():
    for t in list_templates():
        assert abs(sum(s.weight for s in t.sections) - 1.0) < 1e-6, t.id


def test_template_duration_ordering():
    t = load_template("story_v1")
    assert t.duration.min <= t.duration.target <= t.duration.max


def test_template_invalid_weights_rejected(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"id":"bad","name":"Bad","duration":{"min":15,"target":18,"max":22},'
        '"sections":[{"type":"hook","weight":0.5}],"voiceover":true,'
        '"caption_style":"dynamic_center"}'
    )
    with pytest.raises(ValueError):
        TemplateConfig.model_validate_json(bad.read_text())


def test_caption_style_loads():
    c = load_caption_style("dynamic_center")
    assert isinstance(c, CaptionStyleConfig)
    assert c.max_words_per_chunk == 4
    assert 0 < c.safe_zone.bottom < 0.5


def test_unknown_template_raises():
    with pytest.raises(FileNotFoundError):
        load_template("nope_v9")


def test_configs_dir_exists():
    assert (CONFIGS_DIR / "templates").is_dir()
