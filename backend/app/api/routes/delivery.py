"""Delivery API: persona Inbox (token link + QR + public JSON/media) and Telegram sending."""

from __future__ import annotations

import io
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, svc
from app.api.media import ranged_file
from app.config.settings import get_settings
from app.delivery.inbox import check_token, token_for
from app.models import ProjectEvent, ProjectStatus, VideoProject
from app.personas.repo import persona_or_config

log = logging.getLogger(__name__)
router = APIRouter(tags=["delivery"])


def _base_url(request: Request, override: str | None) -> str:
    base = (override or get_settings().public_base_url or "").strip().rstrip("/")
    if base:
        return base
    origin = request.headers.get("origin") or ""
    return origin.rstrip("/") or f"{request.url.scheme}://{request.headers.get('host', 'localhost:3000')}"


# ---------------- inbox link management (app side)
@router.get("/personas/{persona_id}/inbox-link")
def inbox_link(persona_id: str, request: Request, base: str | None = None, db: Session = Depends(get_db)):
    tok = token_for(db, persona_id)
    b = _base_url(request, base)
    return {
        "persona_id": persona_id,
        "token": tok,
        "url": f"{b}/inbox/{persona_id}?key={tok}",
        "base_url": b,
        "qr_url": f"/personas/{persona_id}/inbox-qr.png?base={b}",
    }


@router.post("/personas/{persona_id}/inbox-link/rotate")
def inbox_link_rotate(persona_id: str, request: Request, base: str | None = None, db: Session = Depends(get_db)):
    tok = token_for(db, persona_id, rotate=True)
    b = _base_url(request, base)
    return {"persona_id": persona_id, "token": tok, "url": f"{b}/inbox/{persona_id}?key={tok}", "base_url": b}


@router.get("/personas/{persona_id}/inbox-qr.png")
def inbox_qr(persona_id: str, request: Request, base: str | None = None, db: Session = Depends(get_db)):
    import qrcode

    tok = token_for(db, persona_id)
    url = f"{_base_url(request, base)}/inbox/{persona_id}?key={tok}"
    img = qrcode.make(url, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png", headers={"Cache-Control": "no-store"})


# ---------------- public inbox (token in query; phones open these without logging in)
def _auth(db: Session, persona_id: str, key: str | None) -> None:
    if not check_token(db, persona_id, key):
        raise HTTPException(401, "invalid or missing inbox key")


def _project_item(p: VideoProject, request: Request, db: Session, key: str) -> dict:
    from app.api.routes.projects import _template_kind
    from app.projects.slideshow import SlideshowPipeline

    kind = (p.template_override or {}).get("kind") if p.template_override else _template_kind(p, db)
    item = {
        "id": p.id,
        "topic": p.topic,
        "kind": kind or "video",
        "status": p.status,
        "approved_at": p.approved_at,
        "created_at": p.created_at,
        "duration": p.actual_duration,
        "video_url": None,
        "slides": [],
        "zip_url": None,
        "post_caption": None,
    }
    q = f"?key={key}"
    if kind == "slideshow":
        files = SlideshowPipeline(svc(db, request)).slide_files(p)
        item["slides"] = [f"/inbox/{p.persona_id}/slides/{p.id}/{i + 1}{q}" for i in range(len(files))]
        item["zip_url"] = f"/inbox/{p.persona_id}/zip/{p.id}{q}" if files else None
        sp = svc(db, request).project_dir(p.id) / f"slides_v{p.script_version}.json"
        if sp.is_file():
            import json

            item["post_caption"] = json.loads(sp.read_text()).get("post_caption")
    elif p.current_render_id:
        item["video_url"] = f"/inbox/{p.persona_id}/video/{p.id}{q}"
    return item


@router.get("/inbox/{persona_id}/items")
def inbox_items(persona_id: str, request: Request, key: str | None = None, approved_only: bool = True, db: Session = Depends(get_db)):
    _auth(db, persona_id, key)
    try:
        persona = persona_or_config(db, persona_id)
        name = persona.identity.name if persona.identity else persona.name
    except FileNotFoundError:
        raise HTTPException(404, "persona not found")
    statuses = [ProjectStatus.APPROVED.value] + ([] if approved_only else [ProjectStatus.READY.value])
    rows = db.execute(
        select(VideoProject)
        .where(VideoProject.persona_id == persona_id, VideoProject.status.in_(statuses))
        .order_by(VideoProject.updated_at.desc())
        .limit(60)
    ).scalars()
    return {"persona_id": persona_id, "persona_name": name, "items": [_project_item(p, request, db, key or "") for p in rows]}


def _owned(db: Session, persona_id: str, project_id: str) -> VideoProject:
    p = db.get(VideoProject, project_id)
    if p is None or p.persona_id != persona_id:
        raise HTTPException(404, "not found")
    return p


@router.get("/inbox/{persona_id}/video/{project_id}")
def inbox_video(persona_id: str, project_id: str, request: Request, key: str | None = None, db: Session = Depends(get_db)):
    _auth(db, persona_id, key)
    p = _owned(db, persona_id, project_id)
    path = svc(db, request).project_dir(project_id) / "final.mp4"
    if not p.current_render_id or not path.is_file():
        raise HTTPException(404, "no render")
    return ranged_file(path, request, media_type="video/mp4")


@router.get("/inbox/{persona_id}/slides/{project_id}/{n}")
def inbox_slide(persona_id: str, project_id: str, n: int, request: Request, key: str | None = None, db: Session = Depends(get_db)):
    from app.projects.slideshow import SlideshowPipeline

    _auth(db, persona_id, key)
    p = _owned(db, persona_id, project_id)
    files = SlideshowPipeline(svc(db, request)).slide_files(p)
    if n < 1 or n > len(files):
        raise HTTPException(404, "no such slide")
    return FileResponse(files[n - 1], media_type="image/jpeg")


@router.get("/inbox/{persona_id}/zip/{project_id}")
def inbox_zip(persona_id: str, project_id: str, request: Request, key: str | None = None, db: Session = Depends(get_db)):
    _auth(db, persona_id, key)
    p = _owned(db, persona_id, project_id)
    path = svc(db, request).renders_dir(project_id) / f"slides_v{p.render_version}" / "slides.zip"
    if not p.render_version or not path.is_file():
        raise HTTPException(404, "no slides")
    return FileResponse(path, media_type="application/zip", filename=f"{project_id}_slides.zip")


# ---------------- Telegram
class TelegramSend(BaseModel):
    chat_id: str | None = None  # override the persona's chat


def send_project_to_telegram(db: Session, request: Request, p: VideoProject, chat_id: str | None = None, transport=None) -> dict:
    from app.delivery.telegram import deliver_project
    from app.projects.slideshow import SlideshowPipeline

    persona = persona_or_config(db, p.persona_id)
    chat = chat_id or persona.telegram_chat_id
    if not chat:
        raise RuntimeError("no Telegram chat id for this persona (Personas → edit → Delivery)")
    token = persona.telegram_bot_token
    s = svc(db, request)
    kind = (p.template_override or {}).get("kind") if p.template_override else s.template_for(p).kind
    caption = p.topic
    video = slides = zip_path = None
    if kind == "slideshow":
        slides = SlideshowPipeline(s).slide_files(p)
        sp = s.project_dir(p.id) / f"slides_v{p.script_version}.json"
        if sp.is_file():
            import json

            pc = json.loads(sp.read_text()).get("post_caption")
            if pc:
                caption = f"{p.topic}\n\n{pc}"
        zip_path = s.renders_dir(p.id) / f"slides_v{p.render_version}" / "slides.zip"
    else:
        video = s.project_dir(p.id) / "final.mp4"
    res = deliver_project(
        chat_id=chat, caption=caption, video=video, slides=slides or None, zip_path=zip_path, transport=transport, token=token
    )
    db.add(ProjectEvent(project_id=p.id, stage="DELIVERY", message=f"sent to Telegram chat {chat}: {', '.join(res['sent'])}"))
    db.commit()
    return res


class TelegramTest(BaseModel):
    token: str | None = None  # unsaved token typed in the form; falls back to the persona's saved one
    chat_id: str | None = None


@router.post("/personas/{persona_id}/telegram/test")
def persona_telegram_test(persona_id: str, body: TelegramTest, request: Request, db: Session = Depends(get_db)):
    from app.delivery.telegram import test_bot

    try:
        persona = persona_or_config(db, persona_id)
    except FileNotFoundError:
        raise HTTPException(404, "persona not found")
    token = body.token or persona.telegram_bot_token or get_settings().telegram_bot_token
    if not token:
        return {"ok": False, "message": "no bot token — paste the token from @BotFather"}
    chat = body.chat_id if body.chat_id is not None else persona.telegram_chat_id
    return test_bot(token, chat or None, transport=getattr(request.app.state, "telegram_transport", None))


class TelegramConnect(BaseModel):
    token: str


@router.post("/personas/{persona_id}/telegram/connect")
def persona_telegram_connect(persona_id: str, body: TelegramConnect, request: Request, db: Session = Depends(get_db)):
    """Verify a bot token (getMe) and save it on the persona. Returns the bot name; the chat is picked afterwards."""
    from app.delivery.telegram import test_bot
    from app.personas.repo import get_persona, upsert_persona

    try:
        persona = get_persona(db, persona_id)
    except KeyError:
        raise HTTPException(404, "persona not found")
    token = body.token.strip()
    res = test_bot(token, None, transport=getattr(request.app.state, "telegram_transport", None))
    if not res["ok"]:
        raise HTTPException(422, res["message"])
    persona.telegram_bot_token = token
    upsert_persona(db, persona)
    return {"ok": True, "message": res["message"], "bot": res["message"].split(" ")[0]}


@router.get("/personas/{persona_id}/telegram/chats")
def persona_telegram_chats(persona_id: str, request: Request, db: Session = Depends(get_db)):
    """Chats the persona's bot has seen (after the phone DM'd it / it was added to a group)."""
    from app.delivery.telegram import list_chats

    try:
        persona = persona_or_config(db, persona_id)
    except FileNotFoundError:
        raise HTTPException(404, "persona not found")
    token = persona.telegram_bot_token or get_settings().telegram_bot_token
    if not token:
        raise HTTPException(422, "connect a bot token first")
    try:
        return {"chats": list_chats(token, transport=getattr(request.app.state, "telegram_transport", None))}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Telegram getUpdates failed: {exc}")


class TelegramChat(BaseModel):
    chat_id: str


@router.put("/personas/{persona_id}/telegram/chat")
def persona_telegram_chat(persona_id: str, body: TelegramChat, request: Request, db: Session = Depends(get_db)):
    """Save the chat id and send a hello message through the persona's bot."""
    from app.delivery.telegram import test_bot
    from app.personas.repo import get_persona, upsert_persona

    try:
        persona = get_persona(db, persona_id)
    except KeyError:
        raise HTTPException(404, "persona not found")
    token = persona.telegram_bot_token or get_settings().telegram_bot_token
    if not token:
        raise HTTPException(422, "connect a bot token first")
    persona.telegram_chat_id = body.chat_id.strip()
    upsert_persona(db, persona)
    return test_bot(token, persona.telegram_chat_id, transport=getattr(request.app.state, "telegram_transport", None))


@router.post("/projects/{project_id}/send-telegram")
def project_send_telegram(project_id: str, body: TelegramSend, request: Request, db: Session = Depends(get_db)):
    p = db.get(VideoProject, project_id)
    if p is None:
        raise HTTPException(404, "project not found")
    if p.status not in (ProjectStatus.READY.value, ProjectStatus.APPROVED.value):
        raise HTTPException(409, "render the project first")
    try:
        transport = getattr(request.app.state, "telegram_transport", None)
        return send_project_to_telegram(db, request, p, body.chat_id, transport=transport)
    except RuntimeError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Telegram send failed: {exc}")
