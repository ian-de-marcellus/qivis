"""Shared pytest fixtures for Qivis tests."""

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.main import app


@pytest.fixture
async def client():
    """Async test client for the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
