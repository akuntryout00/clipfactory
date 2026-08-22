"""Multi-persona: personas live in the DB (seeded from configs), assets and projects are persona-scoped."""

import pytest
from app.api.main import create_app
from app.assets.importer import import_assets, migrate_assets_to_persona
from app.assets.selector import find_candidates
from app.config.loaders import CONFIGS_DIR, load_persona
from app.db import Base
from app.llm.fake import FakeLLM
from app.models import Asset
from app.personas.repo import delete_persona, get_persona, list_personas, seed_personas_from_configs, upsert_persona
from app.projects.jobs import InlineJobRunner
from app.schemas.configs import PersonaConfig
from app.voice.fake import FakeVoice
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.conftest import make_clip


def test_seed_personas_from_configs_and_get(session):
    n = seed_personas_from_configs(session, CONFIGS_DIR)
    assert n >= 2
    p = get_persona(session, "michael")
    assert isinstance(p, PersonaConfig) and p.identity and p.identity.name == "Michael"
    assert {x.id for x in list_personas(session)} >= {"michael", "young_professional"}
    assert seed_personas_from_configs(session, CONFIGS_DIR) == 0  # idempotent: existing rows untouched


def test_upsert_and_delete_persona(session):
    cfg = load_persona("young_professional").model_copy(update={"id": "anna", "name": "Anna — Designer"})
    cfg.identity = None
    upsert_persona(session, cfg)
    assert get_persona(session, "anna").name == "Anna — Designer"
    cfg.name = "Anna v2"
    upsert_persona(session, cfg)
    assert get_persona(session, "anna").name == "Anna v2"
    delete_persona(session, "anna")
    with pytest.raises(KeyError):
        get_persona(session, "anna")


def test_import_assigns_persona_from_folder_and_default_for_legacy(session, tmp_path):
    root = tmp_path / "assets"
    make_clip(root / "anna" / "desk" / "typing_01.mp4", seconds=3)
    make_clip(root / "michael" / "phone" / "scroll_01.mp4", seconds=3)
    make_clip(root / "desk" / "legacy_01.mp4", seconds=3)  # old layout → default persona
    seed_personas_from_configs(session, CONFIGS_DIR)
    upsert_persona(session, load_persona("young_professional").model_copy(update={"id": "anna", "name": "Anna"}))
    rep = import_assets(session, root, default_persona="michael")
    assert rep.created == 3
    by_file = {a.file: a for a in session.query(Asset).all()}
    assert by_file["anna/desk/typing_01.mp4"].persona_id == "anna"
    assert by_file["michael/phone/scroll_01.mp4"].persona_id == "michael"
    assert by_file["desk/legacy_01.mp4"].persona_id == "michael"


def test_find_candidates_filters_by_persona(session, mini_assets):
    import_assets(session, mini_assets, default_persona="michael")
    a = session.get(Asset, "asset_001")
    a.persona_id = "anna"
    session.commit()
    ids = {c.asset.id for c in find_candidates(session, ["typing", "laptop", "coffee"], limit=10, persona_id="michael")}
    assert "asset_001" not in ids and ids
    assert {c.asset.id for c in find_candidates(session, ["typing", "laptop"], limit=10, persona_id="anna")} == {"asset_001"}


def test_migrate_assets_moves_files_under_persona_folder(session, mini_assets):
    import_assets(session, mini_assets, default_persona="michael")
    moved = migrate_assets_to_persona(session, mini_assets, "michael")
    assert moved == 6
    a = session.get(Asset, "asset_001")
    assert a.file == "michael/desk/typing_01.mp4" and (mini_assets / a.file).is_file() and a.persona_id == "michael"
    assert not (mini_assets / "desk" / "typing_01.mp4").exists()
    assert migrate_assets_to_persona(session, mini_assets, "michael") == 0  # idempotent
    rep = import_assets(session, mini_assets, default_persona="michael")  # re-import keeps ids / no duplicates
    assert rep.created == 0 and session.query(Asset).count() == 6


@pytest.fixture()
def client(mini_assets, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        seed_personas_from_configs(s, CONFIGS_DIR)
        import_assets(s, mini_assets, default_persona="michael")
    app = create_app(
        session_factory=factory,
        jobs=InlineJobRunner(),
        service_kwargs=dict(
            llm=FakeLLM(),
            voice=FakeVoice(),
            storage_dir=tmp_path / "storage",
            assets_dir=mini_assets,
            render_preset="ultrafast",
            render_crf=30,
        ),
    )
    with TestClient(app) as c:
        yield c


def test_persona_api_crud(client):
    rows = client.get("/personas").json()
    assert {r["id"] for r in rows} >= {"michael", "young_professional"}
    body = {
        **[r for r in rows if r["id"] == "young_professional"][0],
        "id": "anna",
        "name": "Anna — Designer",
        "identity": {"name": "Anna", "age": 29, "location": "Berlin", "background": "product designer"},
    }
    body["voice"] = {
        "provider": "elevenlabs",
        "voice_id": "voice_abc",
        "model_id": "eleven_multilingual_v2",
        "speed": 1.0,
        "stability": 0.5,
        "similarity_boost": 0.75,
        "style": 0.0,
    }
    r = client.post("/personas", json=body)
    assert r.status_code == 201, r.text
    assert client.get("/personas/anna").json()["identity"]["name"] == "Anna"
    body["name"] = "Anna v2"
    assert client.put("/personas/anna", json=body).status_code == 200
    assert client.post("/personas", json=body).status_code == 409  # exists
    bad = {**body, "id": "Bad Id!"}
    assert client.post("/personas", json=bad).status_code == 422
    assert client.delete("/personas/anna").status_code == 204
    assert client.get("/personas/anna").status_code == 404


def test_assets_and_projects_are_persona_scoped(client, tmp_path):
    # create a second persona and upload a clip for it
    base = client.get("/personas/young_professional").json()
    base.update({"id": "anna", "name": "Anna"})
    assert client.post("/personas", json=base).status_code == 201
    clip = make_clip(tmp_path / "n.mp4", seconds=3)
    with clip.open("rb") as f:
        r = client.post(
            "/assets/upload?enrich=false",
            data={"category": "desk", "persona_id": "anna", "approved": "true"},
            files={"file": ("n.mp4", f, "video/mp4")},
        )
    assert r.status_code == 201 and r.json()["persona_id"] == "anna" and r.json()["file"].startswith("anna/desk/")
    assert len(client.get("/assets?persona=anna").json()) == 1
    assert len(client.get("/assets?persona=michael").json()) == 6
    assert client.get("/assets/search?q=typing&persona=anna").json() == [] or all(
        c["asset_id"] for c in client.get("/assets/search?q=typing&persona=anna").json()
    )
    # projects: created for a persona, listed by persona
    r = client.post("/projects", json={"topic": "Real topic here", "template_id": "story_v1", "persona_id": "anna"})
    assert r.status_code == 201 and r.json()["persona_id"] == "anna"
    assert [p["id"] for p in client.get("/projects?persona=anna").json()] == [r.json()["id"]]
    assert client.get("/projects?persona=michael").json() == []
    assert client.post("/projects", json={"topic": "Real topic here", "template_id": "story_v1", "persona_id": "nobody"}).status_code == 404
    # deleting a persona that still owns assets/projects is refused
    assert client.delete("/personas/anna").status_code == 409


def test_seed_repairs_legacy_row_without_voice(session):
    from app.models import Persona
    from app.personas.repo import get_persona, seed_personas_from_configs

    session.add(Persona(id="michael", name="old", config={"id": "michael", "name": "old", "tone": "x"}))
    session.commit()
    assert seed_personas_from_configs(session) >= 1
    cfg = get_persona(session, "michael")
    assert cfg.voice is not None and cfg.identity is not None


def test_unique_persona_id_and_slug(session):
    from app.personas.repo import seed_personas_from_configs, slugify, unique_persona_id

    seed_personas_from_configs(session)
    assert slugify("Anna Müller-Schmidt!") == "anna_muller_schmidt"
    assert unique_persona_id(session, "Michael") == "michael_2"  # michael exists
    assert unique_persona_id(session, "Zoë") == "zoe"


def test_persona_draft_endpoint_returns_valid_persona(client):
    r = client.post(
        "/personas/draft",
        json={
            "name": "Anna",
            "age": 29,
            "location": "Berlin, Germany",
            "language": "de-DE",
            "about": "UX designer at a startup, loves climbing and coffee.",
        },
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["id"] == "anna" and d["identity"]["name"] == "Anna" and d["identity"]["age"] == 29
    assert d["language"] == "de-DE" and d["topics"] and d["tone"] and d["voice"]["provider"] == "elevenlabs"
    # the draft is creatable as-is
    r2 = client.post("/personas", json=d)
    assert r2.status_code == 201, r2.text
    # a second Anna gets a unique id
    r3 = client.post("/personas/draft", json={"name": "Anna", "about": "Another Anna who bakes bread every weekend."})
    assert r3.json()["id"] == "anna_2"


def test_persona_draft_validation(client):
    assert client.post("/personas/draft", json={"name": "", "about": "long enough text here"}).status_code == 422
    assert client.post("/personas/draft", json={"name": "Bob", "about": "short"}).status_code == 422
