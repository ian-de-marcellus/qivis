"""Shared pytest fixtures for Qivis tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.main import app


@pytest.fixture
async def client():
    """Async test client for the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


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
