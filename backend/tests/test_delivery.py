"""Delivery: persona Inbox (token link, public items/media) and Telegram sending (fake transport) incl. auto-send on approve."""

from __future__ import annotations

import io
import shutil

import pytest
from app.delivery.inbox import check_token, token_for
from app.delivery.telegram import deliver_project
from PIL import Image


@pytest.fixture()
def client(mini_assets, tmp_path):
    """API client with fake providers + a recording Telegram transport (no network)."""
    from app.api.main import create_app
    from app.assets.importer import import_assets
    from app.config.settings import REPO_DIR
    from app.db import Base
    from app.llm.fake import FakeLLM
    from app.projects.jobs import InlineJobRunner
    from app.voice.fake import FakeVoice
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from tests.conftest import enable_sqlite_fk

    cfg = tmp_path / "configs"
    shutil.copytree(REPO_DIR / "configs", cfg)
    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}", future=True, connect_args={"check_same_thread": False})
    enable_sqlite_fk(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        import_assets(s, mini_assets)
    calls: list[tuple[str, dict, list[str]]] = []

    def transport(method, data, files):
        calls.append((method, dict(data), sorted((files or {}).keys())))
        return {"ok": True, "result": {}}

    app = create_app(
        session_factory=factory,
        jobs=InlineJobRunner(),
        configs_dir=cfg,
        service_kwargs=dict(llm=FakeLLM(), voice=FakeVoice(), storage_dir=tmp_path / "storage", assets_dir=mini_assets),
        telegram_transport=transport,
    )
    with TestClient(app) as c:
        c.calls = calls  # type: ignore[attr-defined]
        yield c


def test_inbox_tokens(session):
    t1 = token_for(session, "young_professional")
    assert check_token(session, "young_professional", t1) and not check_token(session, "young_professional", "nope")
    assert token_for(session, "young_professional") == t1
    t2 = token_for(session, "young_professional", rotate=True)
    assert t2 != t1 and not check_token(session, "young_professional", t1)


def test_deliver_project_video_and_slides(tmp_path):
    calls = []
    transport = lambda m, d, f: calls.append((m, d, sorted((f or {}).keys()))) or {"ok": True}  # noqa: E731
    v = tmp_path / "final.mp4"
    v.write_bytes(b"0" * 1000)
    r = deliver_project(chat_id="123", caption="hello", video=v, transport=transport)
    assert r["sent"] == ["video"] and calls[0][0] == "sendVideo" and calls[0][2] == ["video"]
    slides = []
    for i in range(12):
        f = tmp_path / f"slide_{i:02d}.jpg"
        Image.new("RGB", (10, 10)).save(f)
        slides.append(f)
    z = tmp_path / "slides.zip"
    z.write_bytes(b"PK")
    calls.clear()
    r = deliver_project(chat_id="123", caption="cap", slides=slides, zip_path=z, transport=transport)
    assert calls[0][0] == "sendMediaGroup" and len(calls[0][2]) == 10 and calls[1][0] == "sendDocument"
    assert "10 slides" in r["sent"] and "zip" in r["sent"]
    with pytest.raises(RuntimeError):
        deliver_project(chat_id="1", caption="x", transport=transport)


def test_inbox_api_and_telegram_on_approve(client, monkeypatch):

    # a finished slideshow project for the persona (skip the real pipeline: mark it READY with slides on disk)
    for i in range(6):
        buf = io.BytesIO()
        Image.new("RGB", (600, 900), (40 * i, 90, 120)).save(buf, format="JPEG")
        assert (
            client.post(
                "/assets/upload",
                files={"file": (f"p{i}.jpg", buf.getvalue(), "image/jpeg")},
                data={
                    "category": "photos",
                    "persona_id": "young_professional",
                    "description": f"photo {i}",
                    "tags": "desk",
                    "approved": "true",
                    "enrich": "false",
                },
            ).status_code
            == 201
        )
    p = client.post(
        "/projects", json={"topic": "Inbox test", "template_id": "slideshow_v1", "persona_id": "young_professional", "target_duration": 15}
    ).json()
    assert client.post(f"/projects/{p['id']}/generate").status_code == 202
    assert client.get(f"/projects/{p['id']}").json()["status"] == "READY"
    # inbox link + QR
    link = client.get("/personas/young_professional/inbox-link?base=http://192.168.1.5:3000").json()
    assert link["url"].startswith("http://192.168.1.5:3000/inbox/young_professional?key=") and link["token"]
    assert client.get("/personas/young_professional/inbox-qr.png").headers["content-type"] == "image/png"
    key = link["token"]
    assert client.get("/inbox/young_professional/items?key=wrong").status_code == 401
    items = client.get(f"/inbox/young_professional/items?key={key}").json()["items"]
    assert items == []  # not approved yet
    items = client.get(f"/inbox/young_professional/items?key={key}&approved_only=false").json()["items"]
    assert len(items) == 1 and items[0]["kind"] == "slideshow" and len(items[0]["slides"]) == 6 and items[0]["zip_url"]
    assert client.get(items[0]["slides"][0]).headers["content-type"] == "image/jpeg"
    assert client.get(items[0]["zip_url"]).status_code == 200
    # telegram: persona without chat id → approve still works, nothing sent; with chat id → sent on approve
    client.calls.clear()
    assert client.post(f"/projects/{p['id']}/approve").status_code == 200
    assert client.calls == []
    client.get("/personas")  # seeds the example personas into this test DB
    per = client.get("/personas/young_professional").json()
    per["telegram_chat_id"] = "-100123"
    per["telegram_bot_token"] = "123456:ABC-secret-token"
    assert client.put("/personas/young_professional", json=per).status_code == 200
    masked = client.get("/personas/young_professional").json()
    assert (
        masked["telegram_bot_token"] is None
        and masked["telegram_bot_token_set"] is True
        and masked["telegram_bot_token_hint"].endswith("oken")
    )
    # saving the masked persona again keeps the secret; "" clears it
    assert client.put("/personas/young_professional", json=masked).status_code == 200
    assert client.get("/personas/young_professional").json()["telegram_bot_token_set"] is True
    t = client.post("/personas/young_professional/telegram/test", json={})
    assert t.status_code == 200 and t.json()["ok"] is True and client.calls[-2][0] == "getMe" and client.calls[-1][0] == "sendMessage"
    client.calls.clear()
    r = client.post(f"/projects/{p['id']}/send-telegram", json={})
    assert r.status_code == 200, r.text
    assert [c[0] for c in client.calls] == ["sendMediaGroup", "sendDocument"] and client.calls[0][1]["chat_id"] == "-100123"
    # rotate invalidates the old key
    client.post("/personas/young_professional/inbox-link/rotate")
    assert client.get(f"/inbox/young_professional/items?key={key}").status_code == 401
    ev = [e["message"] for e in client.get(f"/projects/{p['id']}").json()["events"]]
    assert any("Telegram" in m for m in ev)


def test_telegram_connect_flow(client):
    client.get("/personas")
    # transport answers getMe/getUpdates generically; make getUpdates return one chat
    calls = client.calls
    r = client.post("/personas/young_professional/telegram/connect", json={"token": "111:AAA"})
    assert r.status_code == 200 and r.json()["ok"] and calls[-1][0] == "getMe"
    assert client.get("/personas/young_professional").json()["telegram_bot_token_set"] is True
    r = client.get("/personas/young_professional/telegram/chats")
    assert r.status_code == 200 and calls[-1][0] == "getUpdates" and r.json()["chats"] == []  # fake transport has no updates
    r = client.put("/personas/young_professional/telegram/chat", json={"chat_id": "-100999"})
    assert r.status_code == 200 and r.json()["ok"] and calls[-1][0] == "sendMessage" and calls[-1][1]["chat_id"] == "-100999"
    assert client.get("/personas/young_professional").json()["telegram_chat_id"] == "-100999"
