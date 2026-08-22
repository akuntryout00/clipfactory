"""Provider settings entered in the UI: stored in DB, overlaid on the environment, first-run status, API."""

from __future__ import annotations

import os

import app.config.settings as settings_module
import pytest
from app.config import store
from app.config.settings import Settings, get_settings
from pydantic_settings import SettingsConfigDict

from tests.test_api_ui import client  # noqa: F401


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """Isolate from the developer's real .env so 'cleared' really means unset."""

    class _NoDotenvSettings(Settings):
        model_config = SettingsConfigDict(env_file=None, extra="ignore")

    monkeypatch.setattr(settings_module, "Settings", _NoDotenvSettings)
    for k in ("OPENAI_API_KEY", "ELEVENLABS_API_KEY", "GOOGLE_API_KEY", "FAL_KEY", "LLM_PROVIDER", "VOICE_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    get_settings.cache_clear()
    yield
    store.apply({})
    get_settings.cache_clear()


def test_save_apply_and_clear(session):
    try:
        store.save(session, {"openai_api_key": "sk-test-1234567890", "elevenlabs_api_key": "el-test-abcdef", "openai_model": "gpt-x"})
        s = get_settings()
        assert (
            s.openai_api_key == "sk-test-1234567890" and s.openai_model == "gpt-x" and os.environ["OPENAI_API_KEY"] == "sk-test-1234567890"
        )
        d = store.describe(session)
        assert d["fields"]["openai_api_key"]["value"].endswith("7890") and "sk-test" not in d["fields"]["openai_api_key"]["value"]
        assert d["fields"]["openai_api_key"]["source"] == "ui" and d["fields"]["openai_model"]["value"] == "gpt-x"
        assert d["configured"] is True and d["missing"] == []
        store.save(session, {"openai_api_key": ""})  # clear → env var removed, status shows missing
        assert "OPENAI_API_KEY" not in os.environ and get_settings().openai_api_key is None
        assert store.status()["missing"] == ["openai_api_key"]
    finally:
        store.apply({})
        get_settings.cache_clear()


def test_fake_providers_count_as_configured(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("VOICE_PROVIDER", "fake")
    get_settings.cache_clear()
    try:
        assert store.status()["configured"] is True
    finally:
        get_settings.cache_clear()


def test_settings_api(client, monkeypatch):  # noqa: F811
    r = client.get("/settings/providers")
    assert r.status_code == 200 and "fields" in r.json() and "setup_required" in r.json()
    assert client.put("/settings/providers", json={"nope": 1}).status_code == 422
    assert client.put("/settings/providers", json={"llm_provider": "weird"}).status_code == 422
    try:
        r = client.put("/settings/providers", json={"google_api_key": "g-123456789"})
        assert r.status_code == 200 and r.json()["fields"]["google_api_key"]["set"] is True
        assert client.get("/system").json()["setup_required"] in (True, False)
        r = client.post("/settings/providers/test", json={"provider": "openai", "values": {"openai_api_key": ""}})
        assert r.status_code == 200 and r.json()["ok"] is False  # no key → clear message, no exception
        assert client.post("/settings/providers/test", json={"provider": "nope"}).json()["ok"] is False
    finally:
        client.put("/settings/providers", json={"google_api_key": ""})
        store.apply({})
        get_settings.cache_clear()
