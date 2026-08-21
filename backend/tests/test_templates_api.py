import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.main import create_app
from app.db import Base
from app.llm.fake import FakeLLM
from app.projects.jobs import InlineJobRunner
from app.voice.fake import FakeVoice
from app.config.loaders import CONFIGS_DIR


@pytest.fixture()
def client(mini_assets, tmp_path):
    cfg = tmp_path / "configs"
    shutil.copytree(CONFIGS_DIR, cfg)
    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(session_factory=factory, jobs=InlineJobRunner(),
                     service_kwargs=dict(llm=FakeLLM(), voice=FakeVoice(), storage_dir=tmp_path / "storage", assets_dir=mini_assets),
                     configs_dir=cfg)
    with TestClient(app) as c:
        yield c, cfg


def _body(tid="myshort_v1"):
    return {"id": tid, "name": "My Short", "description": "Two beats", "duration": {"min": 15, "target": 17, "max": 22},
            "sections": [{"type": "hook", "weight": 0.3, "guidance": "punch"}, {"type": "body", "weight": 0.7, "guidance": "explain"}],
            "voiceover": True, "caption_style": "dynamic_center", "music_category": "minimal", "closing": "End on a question.",
            "shot_duration": {"min": 1.5, "max": 4.0}, "overlays": {"min": 1, "max": 2}}


def test_create_template_writes_validated_json(client):
    c, cfg = client
    r = c.post("/templates", json=_body())
    assert r.status_code == 201, r.text
    assert (cfg / "templates" / "myshort_v1.json").is_file()
    assert json.loads((cfg / "templates" / "myshort_v1.json").read_text())["closing"] == "End on a question."
    assert "myshort_v1" in {t["id"] for t in c.get("/templates").json()}


def test_create_rejects_bad_weights_and_duplicate_and_bad_id(client):
    c, _ = client
    bad = _body(); bad["sections"][0]["weight"] = 0.9
    assert c.post("/templates", json=bad).status_code == 422
    assert c.post("/templates", json=_body()).status_code == 201
    assert c.post("/templates", json=_body()).status_code == 409
    bad_id = _body("../evil"); assert c.post("/templates", json=bad_id).status_code == 422


def test_update_and_delete_template(client):
    c, cfg = client
    c.post("/templates", json=_body())
    upd = _body(); upd["name"] = "My Short 2"; upd["sections"][0]["weight"] = 0.4; upd["sections"][1]["weight"] = 0.6
    r = c.put("/templates/myshort_v1", json=upd)
    assert r.status_code == 200 and r.json()["name"] == "My Short 2"
    assert json.loads((cfg / "templates" / "myshort_v1.json").read_text())["sections"][0]["weight"] == 0.4
    # id in body must match path
    mism = _body("other_v1"); assert c.put("/templates/myshort_v1", json=mism).status_code == 422
    assert c.delete("/templates/myshort_v1").status_code == 204
    assert not (cfg / "templates" / "myshort_v1.json").exists()
    assert c.delete("/templates/myshort_v1").status_code == 404


def test_builtin_templates_can_be_edited_but_project_create_uses_new_template(client):
    c, _ = client
    c.post("/templates", json=_body())
    r = c.post("/projects", json={"topic": "Real topic here", "template_id": "myshort_v1"})
    assert r.status_code == 201
