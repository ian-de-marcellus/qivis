"""Shared pytest fixtures for Qivis tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.main import app
from qivis.trees.router import get_tree_service
from qivis.trees.service import TreeService


@pytest.fixture
async def db():
    """In-memory database for tests."""
    database = await Database.connect(":memory:")
    yield database
    await database.close()


@pytest.fixture
async def event_store(db):
    """EventStore backed by in-memory database."""
    return EventStore(db)


@pytest.fixture
async def projector(db):
    """StateProjector backed by in-memory database."""
    return StateProjector(db)


@pytest.fixture
async def client(db):
    """Async test client with in-memory DB wired into the app."""
    service = TreeService(db)
    app.dependency_overrides[get_tree_service] = lambda: service
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
    app.dependency_overrides.clear()
