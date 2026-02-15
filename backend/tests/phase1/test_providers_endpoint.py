"""Tests for GET /api/providers endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.main import app
from qivis.providers.base import GenerationRequest, GenerationResult, LLMProvider, StreamChunk
from qivis.providers.registry import clear_providers, register_provider


class FakeProvider(LLMProvider):
    def __init__(self, provider_name: str):
        self._name = provider_name

    @property
    def name(self) -> str:
        return self._name

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(content="fake", model="fake-model")

    async def generate_stream(self, request: GenerationRequest):  # type: ignore[override]
        yield StreamChunk(type="text_delta", text="fake")


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_providers()
    yield
    clear_providers()


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


class TestProvidersEndpoint:
    async def test_returns_registered_providers(self, client):
        register_provider(FakeProvider("anthropic"))
        register_provider(FakeProvider("openai"))
        resp = await client.get("/api/providers")
        assert resp.status_code == 200
        data = resp.json()
        names = [p["name"] for p in data]
        assert "anthropic" in names
        assert "openai" in names

    async def test_returns_empty_when_none_registered(self, client):
        resp = await client.get("/api/providers")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_provider_entries_have_available_flag(self, client):
        register_provider(FakeProvider("anthropic"))
        resp = await client.get("/api/providers")
        data = resp.json()
        assert all(p["available"] is True for p in data)

    async def test_multiple_providers(self, client):
        register_provider(FakeProvider("anthropic"))
        register_provider(FakeProvider("openai"))
        register_provider(FakeProvider("openrouter"))
        resp = await client.get("/api/providers")
        data = resp.json()
        assert len(data) == 3
