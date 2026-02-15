"""Contract tests for the provider registry."""

import pytest

from qivis.providers.base import GenerationRequest, GenerationResult, LLMProvider, StreamChunk
from qivis.providers.registry import (
    ProviderNotFoundError,
    clear_providers,
    get_all_providers,
    get_provider,
    list_providers,
    register_provider,
)


class FakeProvider(LLMProvider):
    """Minimal provider for testing the registry."""

    @property
    def name(self) -> str:
        return "fake"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(content="fake", model="fake-model")

    async def generate_stream(self, request: GenerationRequest):  # type: ignore[override]
        yield StreamChunk(type="text_delta", text="fake")


class TestProviderRegistry:
    def setup_method(self):
        clear_providers()

    def teardown_method(self):
        clear_providers()

    def test_register_and_get(self):
        provider = FakeProvider()
        register_provider(provider)
        assert get_provider("fake") is provider

    def test_get_unknown_raises(self):
        with pytest.raises(ProviderNotFoundError):
            get_provider("nonexistent")

    def test_clear_empties_registry(self):
        register_provider(FakeProvider())
        clear_providers()
        with pytest.raises(ProviderNotFoundError):
            get_provider("fake")

    def test_list_providers_returns_names(self):
        register_provider(FakeProvider())
        names = list_providers()
        assert names == ["fake"]

    def test_list_providers_empty(self):
        assert list_providers() == []

    def test_get_all_providers_returns_instances(self):
        provider = FakeProvider()
        register_provider(provider)
        all_providers = get_all_providers()
        assert len(all_providers) == 1
        assert all_providers[0] is provider

    def test_get_all_providers_empty(self):
        assert get_all_providers() == []
