"""Batch generation: topic planning, project creation, sequential run, cancel, API."""

from __future__ import annotations

from app.models import Batch, ProjectStatus, VideoProject
from app.projects.batch import BatchService, split_counts

from tests.test_api_ui import client  # noqa: F401
from tests.test_service import svc  # noqa: F401


def test_split_counts_prd_distribution():
    c = split_counts(30, ["story_v1", "list_v1", "pov_v1", "problem_solution_v1"])
    assert c == {"story_v1": 10, "list_v1": 7, "pov_v1": 6, "problem_solution_v1": 7}
    assert sum(split_counts(5, ["story_v1", "pov_v1"]).values()) == 5
    assert split_counts(1, ["list_v1"]) == {"list_v1": 1}


def test_plan_items_ai_and_user_topics(svc, session):  # noqa: F811
    bs = BatchService(session, svc)
    items = bs.plan_items(persona_id="young_professional", count=6, template_ids=None, topics=None)
    assert len(items) == 6 and len({t for t, _ in items}) == 6
    assert {tid for _, tid in items} <= {"story_v1", "list_v1", "pov_v1", "problem_solution_v1"}
    items = bs.plan_items(
        persona_id="young_professional", count=10, template_ids=["pov_v1", "list_v1"], topics=["a topic", "b topic", " c "]
    )
    assert items == [("a topic", "pov_v1"), ("b topic", "list_v1"), ("c", "pov_v1")]


def test_create_and_run_batch(svc, session, monkeypatch):  # noqa: F811
    bs = BatchService(session, svc)
    b = bs.create(persona_id="young_professional", count=3, name="test")
    projects = session.query(VideoProject).filter_by(batch_id=b.id).all()
    assert b.total == 3 and len(projects) == 3 and all(p.status == ProjectStatus.DRAFT.value for p in projects)
    done = []

    def fake_generate(pid):
        p = session.get(VideoProject, pid)
        p.status = ProjectStatus.READY.value if len(done) < 2 else ProjectStatus.FAILED.value
        session.commit()
        done.append(pid)
        if p.status == ProjectStatus.FAILED.value:
            raise RuntimeError("boom")

    monkeypatch.setattr(svc, "generate", fake_generate)
    b = bs.run(b.id)
    assert b.status == "DONE" and len(done) == 3
    s = bs.summary(b)
    assert (s["done"], s["failed"], s["pending"]) == (2, 1, 0)
    # resume re-runs only the failed one
    done.clear()
    bs.run(b.id)
    assert len(done) == 1


def test_cancel_stops_between_items(svc, session, monkeypatch):  # noqa: F811
    bs = BatchService(session, svc)
    b = bs.create(persona_id="young_professional", count=3)
    calls = []

    def fake_generate(pid):
        calls.append(pid)
        p = session.get(VideoProject, pid)
        p.status = ProjectStatus.READY.value
        bb = session.get(Batch, b.id)
        bb.cancel_requested = True  # user hits cancel during the first item
        session.commit()

    monkeypatch.setattr(svc, "generate", fake_generate)
    b = bs.run(b.id)
    assert b.status == "CANCELLED" and len(calls) == 1


def test_batch_api_create_list_cancel(client, monkeypatch):  # noqa: F811
    from app.projects import service as service_mod

    monkeypatch.setattr(service_mod.ProjectService, "generate", lambda self, pid: None)  # inline runner: don't render in tests
    r = client.post("/batches", json={"persona_id": "young_professional", "count": 4, "topics": ["t1", "t2", "t3", "t4"], "name": "api"})
    assert r.status_code == 202, r.text
    d = r.json()
    assert d["total"] == 4 and d["status"] in ("DONE", "RUNNING", "PENDING")
    r = client.get("/batches")
    assert r.status_code == 200 and r.json()[0]["id"] == d["id"]
    r = client.get(f"/batches/{d['id']}")
    assert r.status_code == 200 and len(r.json()["projects"]) == 4 and r.json()["projects"][0]["batch_id"] == d["id"]
    assert client.post(f"/batches/{d['id']}/cancel").status_code == 200
    assert client.post("/batches", json={"persona_id": "young_professional", "count": 0}).status_code == 422
    assert client.post("/batches", json={"persona_id": "nobody", "count": 2}).status_code in (404, 502)
