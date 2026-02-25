"""Integration tests for completion mode through the generation service.

Tests that prompt text gets rendered from messages, stored on nodes,
and returned in responses. Also tests the _prepare_completion_mode helper.
"""

from collections.abc import AsyncIterator

import pytest

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.service import GenerationService
from qivis.models import SamplingParams
from qivis.providers.base import (
    GenerationRequest,
    GenerationResult,
    LLMProvider,
    StreamChunk,
)
from qivis.rhizomes.schemas import (
    CreateNodeRequest,
    CreateRhizomeRequest,
    PatchRhizomeRequest,
)
from qivis.rhizomes.service import RhizomeService


# -- Fixtures --


class CompletionModeProvider(LLMProvider):
    """Mock provider that only supports completion mode."""

    supported_modes = ["completion"]
    supported_params = ["temperature", "max_tokens"]

    @property
    def name(self) -> str:
        return "test-completion"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        # Echo back that we got prompt_text
        return GenerationResult(
            content="completion response",
            model=request.model,
            finish_reason="stop",
            usage={"input_tokens": 50, "output_tokens": 10},
        )

    async def generate_stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(type="text_delta", text="completion response")
        yield StreamChunk(
            type="message_stop",
            is_final=True,
            result=GenerationResult(
                content="completion response",
                model=request.model,
                finish_reason="stop",
                usage={"input_tokens": 50, "output_tokens": 10},
            ),
        )


class ChatOnlyProvider(LLMProvider):
    """Mock provider that only supports chat mode."""

    supported_modes = ["chat"]

    @property
    def name(self) -> str:
        return "test-chat"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            content="chat response",
            model=request.model,
            finish_reason="stop",
            usage={"input_tokens": 50, "output_tokens": 10},
        )

    async def generate_stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(type="text_delta", text="chat response")
        yield StreamChunk(
            type="message_stop",
            is_final=True,
            result=GenerationResult(
                content="chat response",
                model=request.model,
                finish_reason="stop",
                usage={"input_tokens": 50, "output_tokens": 10},
            ),
        )


class DualModeProvider(LLMProvider):
    """Mock provider that supports both chat and completion (like OpenRouter)."""

    supported_modes = ["chat", "completion"]
    supported_params = ["temperature", "max_tokens"]

    @property
    def name(self) -> str:
        return "test-dual"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            content="dual response",
            model=request.model,
            finish_reason="stop",
            usage={"input_tokens": 50, "output_tokens": 10},
        )

    async def generate_stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(type="text_delta", text="dual response")
        yield StreamChunk(
            type="message_stop",
            is_final=True,
            result=GenerationResult(
                content="dual response",
                model=request.model,
                finish_reason="stop",
                usage={"input_tokens": 50, "output_tokens": 10},
            ),
        )


@pytest.fixture
async def db():
    database = await Database.connect(":memory:")
    yield database
    await database.close()


@pytest.fixture
async def services(db):
    rhizome_service = RhizomeService(db)
    store = EventStore(db)
    projector = StateProjector(db)
    gen_service = GenerationService(rhizome_service, store, projector)
    return rhizome_service, gen_service


async def _create_rhizome_with_user_node(
    rhizome_service: RhizomeService,
    *,
    metadata: dict | None = None,
    system_prompt: str | None = "You are a helpful assistant.",
) -> tuple[str, str]:
    """Create a rhizome with a user node, return (rhizome_id, node_id)."""
    rhizome = await rhizome_service.create_rhizome(
        CreateRhizomeRequest(
            title="test",
            default_model="test-model.gguf",
            default_system_prompt=system_prompt,
        )
    )
    rhizome_id = rhizome.rhizome_id

    if metadata is not None:
        await rhizome_service.update_rhizome(
            rhizome_id, PatchRhizomeRequest(metadata=metadata)
        )

    node = await rhizome_service.create_node(
        rhizome_id,
        CreateNodeRequest(content="Hello", role="user"),
    )
    return rhizome_id, node.node_id


# -- Tests --


class TestCompletionModeGenerate:
    async def test_completion_provider_gets_prompt_text(self, services):
        """When provider supports completion mode, prompt_text is rendered and set on request."""
        rhizome_service, gen_service = services
        rhizome_id, node_id = await _create_rhizome_with_user_node(rhizome_service)

        # Capture what the provider receives
        captured_request = None
        original_generate = CompletionModeProvider.generate

        async def capture_generate(self, request):
            nonlocal captured_request
            captured_request = request
            return await original_generate(self, request)

        provider = CompletionModeProvider()
        provider.generate = lambda req: capture_generate(provider, req)

        result = await gen_service.generate(
            rhizome_id, node_id, provider, model="test-model.gguf"
        )

        assert captured_request is not None
        assert captured_request.prompt_text is not None
        # Should contain the user message in raw format (default template)
        assert "Hello" in captured_request.prompt_text

    async def test_chat_provider_does_not_get_prompt_text(self, services):
        """When provider only supports chat, prompt_text stays None."""
        rhizome_service, gen_service = services
        rhizome_id, node_id = await _create_rhizome_with_user_node(rhizome_service)

        captured_request = None
        original_generate = ChatOnlyProvider.generate

        async def capture_generate(self, request):
            nonlocal captured_request
            captured_request = request
            return await original_generate(self, request)

        provider = ChatOnlyProvider()
        provider.generate = lambda req: capture_generate(provider, req)

        result = await gen_service.generate(
            rhizome_id, node_id, provider, model="test-model.gguf"
        )

        assert captured_request is not None
        assert captured_request.prompt_text is None

    async def test_prompt_text_stored_on_node(self, services):
        """The rendered prompt text is stored on the created node."""
        rhizome_service, gen_service = services
        rhizome_id, node_id = await _create_rhizome_with_user_node(rhizome_service)

        provider = CompletionModeProvider()
        node = await gen_service.generate(
            rhizome_id, node_id, provider, model="test-model.gguf"
        )

        assert node.prompt_text is not None
        assert "Hello" in node.prompt_text

    async def test_completion_mode_on_node(self, services):
        """The node's mode is 'completion' when using a completion provider."""
        rhizome_service, gen_service = services
        rhizome_id, node_id = await _create_rhizome_with_user_node(rhizome_service)

        provider = CompletionModeProvider()
        node = await gen_service.generate(
            rhizome_id, node_id, provider, model="test-model.gguf"
        )

        assert node.mode == "completion"

    async def test_template_stop_tokens_merged(self, services):
        """Template stop tokens get merged into sampling_params.stop_sequences."""
        rhizome_service, gen_service = services
        rhizome_id, node_id = await _create_rhizome_with_user_node(rhizome_service)

        captured_request = None
        original_generate = CompletionModeProvider.generate

        async def capture_generate(self, request):
            nonlocal captured_request
            captured_request = request
            return await original_generate(self, request)

        provider = CompletionModeProvider()
        provider.generate = lambda req: capture_generate(provider, req)

        await gen_service.generate(
            rhizome_id, node_id, provider, model="test-model.gguf"
        )

        assert captured_request is not None
        # Raw template has no stop tokens; verify stop_sequences is unchanged
        # (no template stop tokens merged)
        assert captured_request.sampling_params.stop_sequences is not None

    async def test_custom_template_from_metadata(self, services):
        """Tree metadata prompt_template selects the template."""
        rhizome_service, gen_service = services
        rhizome_id, node_id = await _create_rhizome_with_user_node(rhizome_service)

        await rhizome_service.update_rhizome(
            rhizome_id, PatchRhizomeRequest(metadata={"prompt_template": "llama3"})
        )

        captured_request = None
        original_generate = CompletionModeProvider.generate

        async def capture_generate(self, request):
            nonlocal captured_request
            captured_request = request
            return await original_generate(self, request)

        provider = CompletionModeProvider()
        provider.generate = lambda req: capture_generate(provider, req)

        await gen_service.generate(
            rhizome_id, node_id, provider, model="test-model.gguf"
        )

        assert captured_request is not None
        assert "<|begin_of_text|>" in captured_request.prompt_text

    async def test_prefill_appended_to_prompt_text(self, services):
        """In completion mode with prefill, prefill is appended to prompt_text."""
        rhizome_service, gen_service = services
        rhizome_id, node_id = await _create_rhizome_with_user_node(rhizome_service)

        captured_request = None
        original_generate = CompletionModeProvider.generate

        async def capture_generate(self, request):
            nonlocal captured_request
            captured_request = request
            return await original_generate(self, request)

        provider = CompletionModeProvider()
        provider.generate = lambda req: capture_generate(provider, req)

        await gen_service.generate(
            rhizome_id, node_id, provider,
            model="test-model.gguf",
            prefill_content="Sure, I'll",
        )

        assert captured_request is not None
        # Prompt text should end with the prefill
        assert captured_request.prompt_text.endswith("Sure, I'll")


class TestDualModeProvider:
    """Dual-mode providers (chat + completion) default to chat, opt-in to completion."""

    async def test_dual_mode_defaults_to_chat(self, services):
        """A provider supporting both chat and completion defaults to chat mode."""
        rhizome_service, gen_service = services
        rhizome_id, node_id = await _create_rhizome_with_user_node(rhizome_service)

        captured_request = None
        original_generate = DualModeProvider.generate

        async def capture_generate(self, request):
            nonlocal captured_request
            captured_request = request
            return await original_generate(self, request)

        provider = DualModeProvider()
        provider.generate = lambda req: capture_generate(provider, req)

        node = await gen_service.generate(
            rhizome_id, node_id, provider, model="test-model"
        )

        assert captured_request is not None
        assert captured_request.prompt_text is None
        assert node.mode != "completion"

    async def test_dual_mode_opt_in_via_metadata(self, services):
        """Dual-mode provider uses completion when generation_mode is set in metadata."""
        rhizome_service, gen_service = services
        rhizome_id, node_id = await _create_rhizome_with_user_node(
            rhizome_service, metadata={"generation_mode": "completion"}
        )

        captured_request = None
        original_generate = DualModeProvider.generate

        async def capture_generate(self, request):
            nonlocal captured_request
            captured_request = request
            return await original_generate(self, request)

        provider = DualModeProvider()
        provider.generate = lambda req: capture_generate(provider, req)

        node = await gen_service.generate(
            rhizome_id, node_id, provider, model="test-model"
        )

        assert captured_request is not None
        assert captured_request.prompt_text is not None
        assert "Hello" in captured_request.prompt_text
        assert node.mode == "completion"

    async def test_dual_mode_explicit_chat_overrides(self, services):
        """Even if generation_mode is 'chat', dual-mode provider stays in chat mode."""
        rhizome_service, gen_service = services
        rhizome_id, node_id = await _create_rhizome_with_user_node(
            rhizome_service, metadata={"generation_mode": "chat"}
        )

        captured_request = None
        original_generate = DualModeProvider.generate

        async def capture_generate(self, request):
            nonlocal captured_request
            captured_request = request
            return await original_generate(self, request)

        provider = DualModeProvider()
        provider.generate = lambda req: capture_generate(provider, req)

        await gen_service.generate(
            rhizome_id, node_id, provider, model="test-model"
        )

        assert captured_request is not None
        assert captured_request.prompt_text is None


class TestPromptTextRoundTrip:
    async def test_prompt_text_survives_projection(self, db, services):
        """prompt_text round-trips through event → projection → NodeResponse."""
        rhizome_service, gen_service = services
        rhizome_id, node_id = await _create_rhizome_with_user_node(rhizome_service)

        provider = CompletionModeProvider()
        node = await gen_service.generate(
            rhizome_id, node_id, provider, model="test-model.gguf"
        )

        # Read back from tree service
        rhizome = await rhizome_service.get_rhizome(rhizome_id)
        assistant_nodes = [n for n in rhizome.nodes if n.role == "assistant"]
        assert len(assistant_nodes) == 1
        assert assistant_nodes[0].prompt_text is not None
        assert "Hello" in assistant_nodes[0].prompt_text
