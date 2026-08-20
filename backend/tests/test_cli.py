import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

import app.cli as cli
from app.db import Base
from app.llm.fake import FakeLLM
from app.renderer.ffmpeg import ffmpeg_has_filter
from app.voice.fake import FakeVoice

needs_libass = pytest.mark.skipif(not ffmpeg_has_filter("ass"), reason="local ffmpeg lacks libass; runs in Docker")
runner = CliRunner()


@pytest.fixture()
def cli_env(mini_assets, tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'cli.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(cli, "SESSION_FACTORY", factory)
    monkeypatch.setattr(cli, "SERVICE_KWARGS", dict(llm=FakeLLM(), voice=FakeVoice(), storage_dir=tmp_path / "storage",
                                                    assets_dir=mini_assets, render_preset="ultrafast", render_crf=30))
    return tmp_path


def test_assets_import_and_search(cli_env):
    r = runner.invoke(cli.app, ["assets", "import"])
    assert r.exit_code == 0, r.output
    assert "created=6" in r.output
    r = runner.invoke(cli.app, ["assets", "search", "typing", "desk", "close"])
    assert r.exit_code == 0 and "asset_001" in r.output.splitlines()[1]


def test_templates_and_project_create_show(cli_env):
    runner.invoke(cli.app, ["assets", "import"])
    r = runner.invoke(cli.app, ["templates"])
    assert "story_v1" in r.output and "list_v1" in r.output
    r = runner.invoke(cli.app, ["projects", "create", "--template", "story_v1", "--topic", "Stop taking meeting notes manually"])
    assert r.exit_code == 0, r.output
    pid = [l for l in r.output.splitlines() if l.startswith("proj_")][0].strip()
    r = runner.invoke(cli.app, ["projects", "show", pid])
    assert r.exit_code == 0 and "DRAFT" in r.output


def test_plan_only_prints_scene_plan(cli_env):
    runner.invoke(cli.app, ["assets", "import"])
    r = runner.invoke(cli.app, ["generate", "--template", "list_v1", "--topic", "3 productivity habits that waste your time", "--plan-only"])
    assert r.exit_code == 0, r.output
    assert "Script generated" in r.output and "Voice generated" in r.output and "scenes" in r.output
    assert "SCENE 1" in r.output


@needs_libass
def test_generate_end_to_end_cli(cli_env):
    runner.invoke(cli.app, ["assets", "import"])
    r = runner.invoke(cli.app, ["generate", "--template", "list_v1", "--topic", "3 productivity habits that waste your time"])
    assert r.exit_code == 0, r.output
    assert "final.mp4" in r.output and "✓" in r.output
