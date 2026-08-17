"""Tests for long-horizon plan checkpointing.

Exercises the Storage.save_plan / load_plan / list_plans round-trip and
Plan.from_dict rehydration so a crashed session can resume mid-plan.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from okti.agent.plan import Plan, Task, TaskStatus
from okti.storage.db import Storage


@pytest.fixture
async def storage(tmp_path: Path):
    db_path = tmp_path / "test.db"
    s = Storage(db_path=db_path)
    await s.connect()
    yield s
    await s.close()


def _make_plan() -> Plan:
    return Plan(
        scope="add auth",
        summary="two-step",
        tasks=[
            Task(id="t1", title="write model", description="d1",
                 files_involved=["user.py"], status=TaskStatus.COMPLETED),
            Task(id="t2", title="write handler", description="d2",
                 files_involved=["handler.py"], dependencies=["t1"]),
        ],
    )


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_and_load_plan_roundtrip(storage):
    session_id = await storage.create_session(name="test", model="mock")
    plan = _make_plan()

    plan_id = await storage.save_plan(session_id, plan.to_dict())
    assert plan_id  # 12-char hex

    raw = await storage.load_plan(session_id)
    assert raw is not None
    assert raw["scope"] == "add auth"
    assert raw["summary"] == "two-step"
    assert len(raw["tasks"]) == 2

    restored = Plan.from_dict(raw)
    assert restored.scope == "add auth"
    assert len(restored.tasks) == 2
    assert restored.tasks[0].status == TaskStatus.COMPLETED
    assert restored.tasks[1].dependencies == ["t1"]
    assert len(restored.pending_tasks()) == 1


@pytest.mark.asyncio
async def test_save_plan_is_upsert(storage):
    session_id = await storage.create_session(name="test", model="mock")
    plan = _make_plan()

    id1 = await storage.save_plan(session_id, plan.to_dict())

    # Mutate: mark t2 complete and re-save
    plan.tasks[1].status = TaskStatus.COMPLETED
    id2 = await storage.save_plan(session_id, plan.to_dict())

    # Same plan_id — no duplicate row
    assert id1 == id2

    plans = await storage.list_plans()
    plans_for_session = [p for p in plans if p["session_id"] == session_id]
    assert len(plans_for_session) == 1

    reloaded = await storage.load_plan(session_id)
    reloaded_plan = Plan.from_dict(reloaded)
    assert len(reloaded_plan.pending_tasks()) == 0


@pytest.mark.asyncio
async def test_load_plan_missing_returns_none(storage):
    session_id = await storage.create_session(name="empty", model="mock")
    assert await storage.load_plan(session_id) is None


@pytest.mark.asyncio
async def test_list_plans_orders_by_updated(storage):
    s1 = await storage.create_session(name="s1")
    s2 = await storage.create_session(name="s2")
    await storage.save_plan(s1, Plan(scope="first").to_dict())
    await storage.save_plan(s2, Plan(scope="second").to_dict())

    rows = await storage.list_plans()
    scopes = [r["scope"] for r in rows]
    assert "first" in scopes
    assert "second" in scopes
    # Newest first
    assert rows[0]["scope"] == "second"


@pytest.mark.asyncio
async def test_delete_session_cascades_to_plans(storage):
    session_id = await storage.create_session(name="doomed")
    await storage.save_plan(session_id, Plan(scope="disposable").to_dict())
    assert await storage.load_plan(session_id) is not None
    assert await storage.delete_session(session_id) is True
    assert await storage.load_plan(session_id) is None


# ---------------------------------------------------------------------------
# Plan.from_dict resilience
# ---------------------------------------------------------------------------

def test_from_dict_handles_unknown_status():
    raw = {
        "scope": "s", "summary": "",
        "tasks": [{"id": "t", "title": "x", "description": "",
                   "files_involved": [], "dependencies": [],
                   "status": "totally-unknown", "result": None}],
    }
    plan = Plan.from_dict(raw)
    # Falls back to PENDING rather than crashing
    assert plan.tasks[0].status == TaskStatus.PENDING


def test_from_dict_handles_missing_optionals():
    raw = {"scope": "s", "tasks": [{"id": "t", "title": "x", "description": ""}]}
    plan = Plan.from_dict(raw)
    assert plan.tasks[0].files_involved == []
    assert plan.tasks[0].dependencies == []
    assert plan.tasks[0].status == TaskStatus.PENDING
