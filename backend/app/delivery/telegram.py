"""Telegram bot delivery: on approve, send the video (or the slides + zip) to the persona's chat. Bot API limit 50 MB per file."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from app.config.settings import get_settings

log = logging.getLogger(__name__)
API = "https://api.telegram.org"

# injectable transport for tests: (method, data, files) -> dict
Transport = Callable[[str, dict, dict | None], dict]


def _http_transport(token: str) -> Transport:
    import httpx

    def send(method: str, data: dict, files: dict | None) -> dict:
        r = httpx.post(f"{API}/bot{token}/{method}", data=data, files=files, timeout=180)
        try:
            j = r.json()
        except Exception:  # noqa: BLE001
            j = {"ok": False, "description": r.text[:200]}
        if not j.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {j.get('description', j)}")
        return j

    return send


def deliver_project(
    *,
    chat_id: str,
    caption: str,
    video: Path | None = None,
    slides: list[Path] | None = None,
    zip_path: Path | None = None,
    transport: Transport | None = None,
    token: str | None = None,
) -> dict:
    """Send one project: video → sendVideo; slideshow → sendMediaGroup (≤10 photos) + zip as document. Returns a summary.
    `token` = the persona's own bot; falls back to the global TELEGRAM_BOT_TOKEN."""
    token = token or get_settings().telegram_bot_token
    if transport is None:
        if not token:
            raise RuntimeError("no Telegram bot token for this persona (Personas → edit → Delivery)")
        transport = _http_transport(token)
    sent: list[str] = []
    cap = caption[:1000]
    if video is not None and video.is_file():
        if video.stat().st_size > 50 * 1024 * 1024:
            raise RuntimeError("video is larger than Telegram's 50 MB bot limit")
        with video.open("rb") as fh:
            transport(
                "sendVideo", {"chat_id": chat_id, "caption": cap, "supports_streaming": "true"}, {"video": (video.name, fh, "video/mp4")}
            )
        sent.append("video")
    if slides:
        import json

        chunk = slides[:10]
        files = {f"photo{i}": (f.name, f.open("rb"), "image/jpeg") for i, f in enumerate(chunk)}
        media = [{"type": "photo", "media": f"attach://photo{i}", **({"caption": cap} if i == 0 else {})} for i in range(len(chunk))]
        try:
            transport("sendMediaGroup", {"chat_id": chat_id, "media": json.dumps(media)}, files)
        finally:
            for _, fh, _ in files.values():
                fh.close()
        sent.append(f"{len(chunk)} slides")
        if len(slides) > 10:
            sent.append(f"({len(slides) - 10} more in the zip)")
    if zip_path is not None and zip_path.is_file():
        with zip_path.open("rb") as fh:
            transport(
                "sendDocument", {"chat_id": chat_id, "caption": "All slides (zip)"}, {"document": (zip_path.name, fh, "application/zip")}
            )
        sent.append("zip")
    if not sent:
        raise RuntimeError("nothing to send — render the project first")
    return {"chat_id": chat_id, "sent": sent}


def test_bot(token: str, chat_id: str | None = None, transport: Transport | None = None) -> dict:
    """getMe (+ a hello message when a chat id is given). Never raises."""
    try:
        t = transport or _http_transport(token)
        me = t("getMe", {}, None)
        name = (me.get("result") or {}).get("username")
        if chat_id:
            t(
                "sendMessage",
                {"chat_id": chat_id, "text": "ClipFactory connected — approved videos for this persona will arrive here."},
                None,
            )
            return {"ok": True, "message": f"@{name} OK · test message sent to {chat_id}"}
        return {"ok": True, "message": f"@{name} OK · add a chat id to receive videos"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc)[:300]}


def list_chats(token: str, transport: Transport | None = None) -> list[dict]:
    """Chats the bot has seen recently (getUpdates): lets the UI pick a chat id after the user DMs the bot / adds it to a group."""
    t = transport or _http_transport(token)
    res = t("getUpdates", {"limit": 100, "allowed_updates": '["message","channel_post","my_chat_member"]'}, None)
    seen: dict[str, dict] = {}
    for u in res.get("result") or []:
        msg = (
            u.get("message")
            or u.get("channel_post")
            or (u.get("my_chat_member") or {}).get("chat")
            and {"chat": u["my_chat_member"]["chat"]}
        )
        chat = (msg or {}).get("chat") if isinstance(msg, dict) else None
        if not chat:
            continue
        cid = str(chat.get("id"))
        title = (
            chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("username") or cid
        )
        seen[cid] = {"id": cid, "title": title, "type": chat.get("type"), "username": chat.get("username")}
    return list(seen.values())
