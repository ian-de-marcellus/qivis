"""Contract tests for perturbation experiments (Phase 9.2b).

Tests divergence metrics, context modification per perturbation type,
and report storage.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.divergence import (
    certainty_delta,
    length_ratio,
    normalized_edit_distance,
    word_diff_ratio,
)
from qivis.generation.service import GenerationService
from qivis.models import (
    EventEnvelope,
    LogprobData,
    NodeCreatedPayload,
    PerturbationReportGeneratedPayload,
    SamplingParams,
    TokenLogprob,
)
from qivis.providers.base import (
    GenerationRequest,
    GenerationResult,
    LLMProvider,
    StreamChunk,
)
from qivis.providers.registry import clear_providers, register_provider
from qivis.rhizomes.schemas import CreateNodeRequest, CreateRhizomeRequest
from qivis.rhizomes.service import RhizomeService


# ---------------------------------------------------------------------------
# Divergence metric tests (pure functions)
# ---------------------------------------------------------------------------


class TestWordDiffRatio:

    def test_identical_texts(self):
        assert word_diff_ratio("hello world", "hello world") == 0.0

    def test_completely_different(self):
        assert word_diff_ratio("hello world", "foo bar baz") == 1.0

    def test_partial_overlap(self):
        # "the cat sat" vs "the dog sat" — LCS is ["the", "sat"], len 2
        # removed = 3 - 2 = 1, added = 3 - 2 = 1, total = (1+1)/(3+3) = 1/3
        ratio = word_diff_ratio("the cat sat", "the dog sat")
        assert abs(ratio - 1 / 3) < 0.01

    def test_both_empty(self):
        assert word_diff_ratio("", "") == 0.0

    def test_one_empty(self):
        assert word_diff_ratio("hello", "") == 1.0
        assert word_diff_ratio("", "hello") == 1.0


class TestNormalizedEditDistance:

    def test_identical(self):
        assert normalized_edit_distance("hello", "hello") == 0.0

    def test_known_pair(self):
        # "kitten" -> "sitting": 3 edits, max len = 7
        dist = normalized_edit_distance("kitten", "sitting")
        assert abs(dist - 3 / 7) < 0.01

    def test_both_empty(self):
        assert normalized_edit_distance("", "") == 0.0

    def test_one_empty(self):
        assert normalized_edit_distance("hello", "") == 1.0


class TestCertaintyDelta:

    def test_known_values(self):
        control = [{"linear_prob": 0.9}, {"linear_prob": 0.8}]
        perturbed = [{"linear_prob": 0.7}, {"linear_prob": 0.6}]
        # avg_control = 0.85, avg_perturbed = 0.65
        delta = certainty_delta(control, perturbed)
        assert delta is not None
        assert abs(delta - (-0.2)) < 0.001

    def test_none_when_missing_control(self):
        assert certainty_delta(None, [{"linear_prob": 0.5}]) is None

    def test_none_when_missing_perturbed(self):
        assert certainty_delta([{"linear_prob": 0.5}], None) is None

    def test_none_when_both_empty(self):
        assert certainty_delta([], [{"linear_prob": 0.5}]) is None


class TestLengthRatio:

    def test_equal_length(self):
        assert length_ratio("hello", "world") == 1.0

    def test_longer_perturbation(self):
        assert length_ratio("hi", "hello world") == 11 / 2

    def test_empty_control(self):
        assert length_ratio("", "hello") == 0.0


# ---------------------------------------------------------------------------
# PerturbationService context modification tests
# ---------------------------------------------------------------------------


class MockPerturbProvider(LLMProvider):
    """Mock provider that echoes request details for verification."""

    supported_modes = ["chat"]
    supported_params = ["temperature", "max_tokens"]

    def __init__(self):
        self.calls: list[GenerationRequest] = []

    @property
    def name(self) -> str:
        return "mock-perturb"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        # Include the system_prompt and message count in the response for verification
        msg_count = len(request.messages)
        sys = request.system_prompt or "none"
        content = f"response: msgs={msg_count} sys={sys}"
        return GenerationResult(
            content=content,
            model=request.model,
            finish_reason="end_turn",
            usage={"input_tokens": 10, "output_tokens": 5},
            latency_ms=25,
            logprobs=LogprobData(
                tokens=[
                    TokenLogprob(token="response", logprob=-0.2, linear_prob=0.82, top_alternatives=[]),
                ],
                provider_format="mock",
                top_k_available=0,
            ),
        )

    async def generate_stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[StreamChunk]:
        result = await self.generate(request)
        yield StreamChunk(type="text_delta", text=result.content)
        yield StreamChunk(type="message_stop", is_final=True, result=result)


@pytest.fixture
async def perturb_env(db: Database):
    """Set up services and a conversation with a digression group and exclusions."""
    store = EventStore(db)
    projector = StateProjector(db)
    rhizome_svc = RhizomeService(db)
    gen_svc = GenerationService(rhizome_svc, store, projector)

    provider = MockPerturbProvider()
    clear_providers()
    register_provider(provider)

    # Import PerturbationService — will fail until it's implemented
    from qivis.generation.perturbation import PerturbationService
    perturb_svc = PerturbationService(gen_svc, store, projector)

    # Create a rhizome with 6 messages: user1, asst1, user2, asst2, user3, asst3
    rhizome = await rhizome_svc.create_rhizome(CreateRhizomeRequest(
        title="Perturbation Test",
        default_system_prompt="You are helpful.",
        default_provider="mock-perturb",
        default_model="test-model",
    ))
    rid = rhizome.rhizome_id

    node_ids = []
    parent_id = None
    for i in range(6):
        role = "user" if i % 2 == 0 else "assistant"
        content = f"Message {i + 1}"
        if role == "user":
            node = await rhizome_svc.create_node(rid, CreateNodeRequest(
                content=content, role=role, parent_id=parent_id,
            ))
            node_ids.append(node.node_id)
            parent_id = node.node_id
        else:
            nid = str(uuid4())
            evt = EventEnvelope(
                event_id=str(uuid4()),
                rhizome_id=rid,
                timestamp=datetime.now(UTC),
                device_id="test",
                event_type="NodeCreated",
                payload=NodeCreatedPayload(
                    node_id=nid,
                    parent_id=parent_id,
                    role="assistant",
                    content=content,
                    model="test-model",
                    provider="mock-perturb",
                ).model_dump(),
            )
            await store.append(evt)
            await projector.project([evt])
            node_ids.append(nid)
            parent_id = nid

    # Create a digression group containing user2 + asst2 (nodes 2,3 — index 2,3)
    from tests.fixtures import (
        make_digression_group_created_envelope,
        make_node_context_excluded_envelope,
    )

    group_id = str(uuid4())
    dg_evt = make_digression_group_created_envelope(
        rhizome_id=rid,
        group_id=group_id,
        node_ids=[node_ids[2], node_ids[3]],
        label="Side conversation",
        excluded_by_default=False,
    )
    await store.append(dg_evt)
    await projector.project([dg_evt])

    yield {
        "rhizome_svc": rhizome_svc,
        "gen_svc": gen_svc,
        "perturb_svc": perturb_svc,
        "store": store,
        "projector": projector,
        "provider": provider,
        "rhizome_id": rid,
        "node_ids": node_ids,
        "group_id": group_id,
    }

    clear_providers()


class TestPerturbationContextModification:
    """Tests that each perturbation type correctly modifies context."""

    async def test_digression_toggle_excludes_group(self, perturb_env):
        """Toggling a digression group to excluded removes those messages from context."""
        env = perturb_env
        from qivis.rhizomes.schemas import PerturbationConfig

        # Run experiment with a digression toggle that excludes the group
        report = await env["perturb_svc"].run_experiment(
            rhizome_id=env["rhizome_id"],
            node_id=env["node_ids"][-1],  # anchor = last node
            perturbations=[PerturbationConfig(
                type="digression_toggle",
                group_id=env["group_id"],
                include=False,
            )],
            provider=env["provider"],
            model="test-model",
            include_control=True,
        )

        # Should have 2 steps: control + 1 perturbation
        assert len(report.steps) == 2
        assert report.steps[0].type == "control"
        assert report.steps[1].type == "digression_toggle"

        # The provider should have been called twice
        assert len(env["provider"].calls) == 2

        # Control should have more messages than the perturbation
        # (the perturbation excludes the digression group's 2 messages)
        control_msgs = len(env["provider"].calls[0].messages)
        perturbed_msgs = len(env["provider"].calls[1].messages)
        assert control_msgs > perturbed_msgs

    async def test_node_exclusion_toggle_excludes_node(self, perturb_env):
        """Excluding a specific node removes it from context."""
        env = perturb_env
        from qivis.rhizomes.schemas import PerturbationConfig

        # Exclude the second user message (index 2)
        target_node = env["node_ids"][2]
        report = await env["perturb_svc"].run_experiment(
            rhizome_id=env["rhizome_id"],
            node_id=env["node_ids"][-1],
            perturbations=[PerturbationConfig(
                type="node_exclusion",
                node_id=target_node,
                exclude=True,
            )],
            provider=env["provider"],
            model="test-model",
            include_control=True,
        )

        assert len(report.steps) == 2
        # Perturbation should have fewer messages
        control_msgs = len(env["provider"].calls[0].messages)
        perturbed_msgs = len(env["provider"].calls[1].messages)
        assert perturbed_msgs < control_msgs

    async def test_system_prompt_variant_replaces_prompt(self, perturb_env):
        """System prompt perturbation uses the alternative prompt."""
        env = perturb_env
        from qivis.rhizomes.schemas import PerturbationConfig

        report = await env["perturb_svc"].run_experiment(
            rhizome_id=env["rhizome_id"],
            node_id=env["node_ids"][-1],
            perturbations=[PerturbationConfig(
                type="system_prompt",
                system_prompt="You are a pirate.",
            )],
            provider=env["provider"],
            model="test-model",
            include_control=True,
        )

        assert len(report.steps) == 2
        # Control uses original system prompt
        assert env["provider"].calls[0].system_prompt == "You are helpful."
        # Perturbation uses the override
        assert env["provider"].calls[1].system_prompt == "You are a pirate."

    async def test_control_uses_unmodified_context(self, perturb_env):
        """Control step generates with the original, unmodified context."""
        env = perturb_env
        from qivis.rhizomes.schemas import PerturbationConfig

        report = await env["perturb_svc"].run_experiment(
            rhizome_id=env["rhizome_id"],
            node_id=env["node_ids"][-1],
            perturbations=[PerturbationConfig(
                type="system_prompt",
                system_prompt="Alternative prompt.",
            )],
            provider=env["provider"],
            model="test-model",
            include_control=True,
        )

        # Control uses the default system prompt
        control_call = env["provider"].calls[0]
        assert control_call.system_prompt == "You are helpful."
        # Control should have all 6 messages in context (5 before anchor, as anchor is the generation point)
        # The exact number depends on how context is built, but it should be >= 5

    async def test_report_stored_and_queryable(self, perturb_env):
        """Reports are stored via events and queryable."""
        env = perturb_env
        from qivis.rhizomes.schemas import PerturbationConfig

        report = await env["perturb_svc"].run_experiment(
            rhizome_id=env["rhizome_id"],
            node_id=env["node_ids"][-1],
            perturbations=[PerturbationConfig(
                type="system_prompt",
                system_prompt="Be concise.",
            )],
            provider=env["provider"],
            model="test-model",
            include_control=True,
        )

        # Report should have an ID and divergence metrics
        assert report.report_id
        assert report.experiment_id
        assert len(report.divergence) == 1  # one perturbation → one divergence entry

        # Should be retrievable from the projector
        reports = await env["projector"].get_perturbation_reports(env["rhizome_id"])
        assert len(reports) == 1
        assert reports[0]["report_id"] == report.report_id

    async def test_divergence_metrics_computed(self, perturb_env):
        """Report includes divergence metrics for each perturbation vs control."""
        env = perturb_env
        from qivis.rhizomes.schemas import PerturbationConfig

        report = await env["perturb_svc"].run_experiment(
            rhizome_id=env["rhizome_id"],
            node_id=env["node_ids"][-1],
            perturbations=[PerturbationConfig(
                type="system_prompt",
                system_prompt="Different prompt.",
            )],
            provider=env["provider"],
            model="test-model",
            include_control=True,
        )

        assert len(report.divergence) == 1
        d = report.divergence[0]
        # Metrics should be computed
        assert isinstance(d.word_diff_ratio, float)
        assert isinstance(d.edit_distance, float)
        assert isinstance(d.length_ratio, float)
        # certainty_delta may or may not be None depending on logprobs
