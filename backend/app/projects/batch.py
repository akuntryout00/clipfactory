"""Batch generation (PRD §51): pick N topics (AI or user-supplied), create N projects, generate them sequentially."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.loaders import list_templates, load_template
from app.models import Batch, BatchStatus, ProjectStatus, VideoProject
from app.projects.service import ProjectService

log = logging.getLogger(__name__)

# PRD §51 distribution for the 30-video validation batch, used as weights for any count
DEFAULT_WEIGHTS = {"story_v1": 10, "list_v1": 7, "pov_v1": 6, "problem_solution_v1": 7}
MAX_BATCH = 60


def split_counts(total: int, template_ids: list[str], weights: dict[str, int] | None = None) -> dict[str, int]:
    """Largest-remainder split of `total` over templates by weight (equal if a template has no weight)."""
    w = {t: float((weights or DEFAULT_WEIGHTS).get(t, 1)) for t in template_ids}
    sw = sum(w.values()) or 1.0
    raw = {t: total * w[t] / sw for t in template_ids}
    counts = {t: int(raw[t]) for t in template_ids}
    for t in sorted(template_ids, key=lambda t: raw[t] - counts[t], reverse=True)[: total - sum(counts.values())]:
        counts[t] += 1
    return counts


class BatchService:
    def __init__(self, session: Session, svc: ProjectService):
        self.session = session
        self.svc = svc

    # ---------------- creation
    def plan_items(
        self,
        *,
        persona_id: str,
        count: int,
        template_ids: list[str] | None,
        topics: list[str] | None,
    ) -> list[tuple[str, str]]:
        """→ [(topic, template_id)] — user topics round-robin over templates, otherwise AI topics per template count."""
        count = max(1, min(MAX_BATCH, int(count)))
        all_ids = [t.id for t in list_templates(self.svc.configs_dir)]
        tids = [t for t in (template_ids or all_ids) if t in all_ids] or all_ids
        if topics:
            clean = [t.strip() for t in topics if t and t.strip()][:count]
            return [(topic, tids[i % len(tids)]) for i, topic in enumerate(clean)]
        counts = split_counts(count, tids)
        persona = self.svc._persona(persona_id)
        templates = [load_template(t, self.svc.configs_dir) for t in tids]
        used = [
            r[0]
            for r in self.session.execute(
                select(VideoProject.topic).where(VideoProject.persona_id == persona_id).order_by(VideoProject.created_at.desc()).limit(80)
            ).all()
        ]
        out = self.svc.llm.generate_topics(persona=persona, templates=templates, counts=counts, exclude=used)
        items: list[tuple[str, str]] = []
        seen: set[str] = set()
        for it in out.items:
            key = it.topic.strip().lower()
            if not key or key in seen or it.template_id not in tids:
                continue
            seen.add(key)
            items.append((it.topic.strip()[:300], it.template_id))
        # top up / trim to the requested count
        i = 0
        while len(items) < count and out.items:
            src = out.items[i % len(out.items)]
            items.append((f"{src.topic.strip()[:280]} ({len(items) + 1})", src.template_id if src.template_id in tids else tids[0]))
            i += 1
        return items[:count]

    def create(
        self,
        *,
        persona_id: str,
        count: int,
        template_ids: list[str] | None = None,
        topics: list[str] | None = None,
        target_duration: float | None = None,
        name: str | None = None,
    ) -> Batch:
        items = self.plan_items(persona_id=persona_id, count=count, template_ids=template_ids, topics=topics)
        if not items:
            raise ValueError("no topics to generate")
        batch = Batch(
            persona_id=persona_id,
            name=name or f"Batch of {len(items)}",
            total=len(items),
            config={
                "count": count,
                "template_ids": template_ids,
                "topics_source": "user" if topics else "ai",
                "target_duration": target_duration,
            },
        )
        self.session.add(batch)
        self.session.flush()
        for topic, tid in items:
            p = self.svc.create_project(topic=topic, template_id=tid, persona_id=persona_id, target_duration=target_duration)
            p.batch_id = batch.id
        self.session.commit()
        return batch

    # ---------------- execution
    def run(self, batch_id: str) -> Batch:
        b = self.session.get(Batch, batch_id)
        if b is None:
            raise KeyError(batch_id)
        b.status = BatchStatus.RUNNING.value
        self.session.commit()
        projects = (
            self.session.execute(select(VideoProject).where(VideoProject.batch_id == batch_id).order_by(VideoProject.created_at))
            .scalars()
            .all()
        )
        for p in projects:
            self.session.refresh(b)
            if b.cancel_requested:
                b.status = BatchStatus.CANCELLED.value
                b.finished_at = datetime.now(UTC)
                self.session.commit()
                return b
            if p.status not in (ProjectStatus.DRAFT.value, ProjectStatus.FAILED.value):
                continue  # already done (resume)
            try:
                self.svc.generate(p.id)
            except Exception as exc:  # noqa: BLE001 — persisted on the project; the batch continues
                log.warning("batch %s: project %s failed: %s", batch_id, p.id, exc)
        self.session.refresh(b)
        b.status = BatchStatus.CANCELLED.value if b.cancel_requested else BatchStatus.DONE.value
        b.finished_at = datetime.now(UTC)
        self.session.commit()
        return b

    def cancel(self, batch_id: str) -> Batch:
        b = self.session.get(Batch, batch_id)
        if b is None:
            raise KeyError(batch_id)
        if b.status in (BatchStatus.PENDING.value, BatchStatus.RUNNING.value):
            b.cancel_requested = True
            if b.status == BatchStatus.PENDING.value:
                b.status = BatchStatus.CANCELLED.value
                b.finished_at = datetime.now(UTC)
        self.session.commit()
        return b

    # ---------------- reporting
    def summary(self, b: Batch) -> dict:
        rows = self.session.execute(select(VideoProject.status).where(VideoProject.batch_id == b.id)).all()
        c = Counter(r[0] for r in rows)
        running = sum(v for k, v in c.items() if k not in ("DRAFT", "READY", "APPROVED", "FAILED"))
        return {
            "id": b.id,
            "persona_id": b.persona_id,
            "name": b.name,
            "status": b.status,
            "total": b.total,
            "done": c.get("READY", 0) + c.get("APPROVED", 0),
            "failed": c.get("FAILED", 0),
            "running": running,
            "pending": c.get("DRAFT", 0),
            "approved": c.get("APPROVED", 0),
            "config": b.config or {},
            "error": b.error,
            "cancel_requested": bool(b.cancel_requested),
            "created_at": b.created_at,
            "updated_at": b.updated_at,
            "finished_at": b.finished_at,
        }
