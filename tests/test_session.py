"""Tests for session auto-save, resume, and incremental save."""

import pytest
from oktigent.config import OktigentConfig
from oktigent.storage.db import Storage
from oktigent.models.provider import Message, Role


@pytest.fixture
def config():
    return OktigentConfig()


@pytest.fixture
async def storage(tmp_path):
    """Create a temporary storage instance."""
    db_path = tmp_path / "test.db"
    s = Storage(db_path=db_path)
    await s.connect()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# Storage: get_latest_session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_latest_session_empty(storage):
    """No sessions exist yet."""
    result = await storage.get_latest_session()
    assert result is None


@pytest.mark.asyncio
async def test_get_latest_session(storage):
    """Returns the most recently updated session."""
    _ = await storage.create_session(name="first", workspace="/tmp")
    sid2 = await storage.create_session(name="second", workspace="/tmp")

    latest = await storage.get_latest_session()
    assert latest is not None
    assert latest["id"] == sid2  # most recent


@pytest.mark.asyncio
async def test_get_latest_session_by_workspace(storage):
    """Filters by workspace."""
    sid1 = await storage.create_session(name="proj-a", workspace="/a")
    _ = await storage.create_session(name="proj-b", workspace="/b")

    latest = await storage.get_latest_session(workspace="/a")
    assert latest is not None
    assert latest["id"] == sid1


# ---------------------------------------------------------------------------
# Storage: get_message_count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_message_count_empty(storage):
    sid = await storage.create_session()
    count = await storage.get_message_count(sid)
    assert count == 0


@pytest.mark.asyncio
async def test_get_message_count(storage):
    sid = await storage.create_session()
    await storage.add_message(sid, Message(role=Role.USER, content="hello"))
    await storage.add_message(sid, Message(role=Role.ASSISTANT, content="hi"))
    count = await storage.get_message_count(sid)
    assert count == 2


# ---------------------------------------------------------------------------
# Storage: delete_session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_session(storage):
    sid = await storage.create_session()
    await storage.add_message(sid, Message(role=Role.USER, content="test"))
    deleted = await storage.delete_session(sid)
    assert deleted is True

    session = await storage.get_session(sid)
    assert session is None


@pytest.mark.asyncio
async def test_delete_session_nonexistent(storage):
    deleted = await storage.delete_session("nonexistent")
    assert deleted is False


# ---------------------------------------------------------------------------
# Auto-save config
# ---------------------------------------------------------------------------

def test_auto_save_default_true():
    config = OktigentConfig()
    assert config.auto_save is True


def test_auto_save_can_disable():
    config = OktigentConfig()
    config.auto_save = False
    assert config.auto_save is False
