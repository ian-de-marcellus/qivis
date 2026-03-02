"""Integration tests for perturbation experiments through the API (Phase 9.2b).

Tests endpoint behavior, SSE streaming, and report persistence.
"""

import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.db.connection import Database
from qivis.events.projector import StateProjector
from qivis.events.store import EventStore
from qivis.generation.perturbation import PerturbationService
from qivis.generation.service import GenerationService
from qivis.models import LogprobData, TokenLogprob
from qivis.providers.base import (
    GenerationRequest,
    GenerationResult,
    LLMProvider,
    StreamChunk,
)
from qivis.providers.registry import clear_providers, register_provider
from qivis.main import app
from qivis.rhizomes.router import (
    get_generation_service,
    get_perturbation_service,
    get_rhizome_service,
)
from qivis.rhizomes.service import RhizomeService
from tests.fixtures import create_rhizome_with_messages


# -- Mock provider --


class PerturbRecordingProvider(LLMProvider):
    """Provider that returns different content based on the system prompt."""

    supported_modes = ["chat"]
    supported_params = ["temperature", "max_tokens"]

    def __init__(self):
        self.calls: list[GenerationRequest] = []

    @property
    def name(self) -> str:
        return "perturb-provider"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        # Vary response based on system prompt so divergence metrics are non-trivial
        sys = request.system_prompt or ""
        if "pirate" in sys.lower():
            content = "Arrr, matey! The ocean be vast and full of treasure."
        elif "concise" in sys.lower():
            content = "Yes."
        else:
            content = "I'd be happy to help with your question about this topic."

        return GenerationResult(
            content=content,
            model=request.model,
            finish_reason="end_turn",
            usage={"input_tokens": 20, "output_tokens": 10},
            latency_ms=50,
            logprobs=LogprobData(
                tokens=[
                    TokenLogprob(token="word", logprob=-0.1, linear_prob=0.9, top_alternatives=[]),
                    TokenLogprob(token="two", logprob=-0.3, linear_prob=0.74, top_alternatives=[]),
                ],
                provider_format="mock",
                top_k_available=0,
            ),
        )

    async def generate_stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[StreamChunk]:
        result = await self.generate(request)
        # Stream in two chunks
        half = len(result.content) // 2
        yield StreamChunk(type="text_delta", text=result.content[:half])
        yield StreamChunk(type="text_delta", text=result.content[half:])
        yield StreamChunk(type="message_stop", is_final=True, result=result)


# -- Fixtures --


@pytest.fixture
async def api_client(db: Database) -> AsyncIterator[tuple[AsyncClient, dict]]:
    """Test client with perturbation service wired in."""
    store = EventStore(db)
    projector = StateProjector(db)
    rhizome_svc = RhizomeService(db)
    gen_svc = GenerationService(rhizome_svc, store, projector)

    provider = PerturbRecordingProvider()
    clear_providers()
    register_provider(provider)

    perturb_svc = PerturbationService(gen_svc, store, projector)

    app.dependency_overrides[get_rhizome_service] = lambda: rhizome_svc
    app.dependency_overrides[get_generation_service] = lambda: gen_svc
    app.dependency_overrides[get_perturbation_service] = lambda: perturb_svc

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, {"provider": provider}

    app.dependency_overrides.clear()
    clear_providers()


async def _create_conversation(client: AsyncClient) -> dict:
    """Create a 4-message conversation."""
    return await create_rhizome_with_messages(client, n_messages=4)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestPerturbationEndpoint:

    async def test_full_experiment_with_perturbations(self, api_client):
        """Full experiment with control + 2 system prompt perturbations."""
        client, extras = api_client
        conv = await _create_conversation(client)

        resp = await client.post(
            f"/api/rhizomes/{conv['rhizome_id']}/nodes/{conv['node_ids'][-1]}/perturb",
            json={
                "perturbations": [
                    {"type": "system_prompt", "system_prompt": "You are a pirate."},
                    {"type": "system_prompt", "system_prompt": "Be concise."},
                ],
                "provider": "perturb-provider",
                "include_control": True,
                "stream": False,
            },
        )
        assert resp.status_code == 200
        report = resp.json()

        # 3 steps: control + 2 perturbations
        assert len(report["steps"]) == 3
        assert report["steps"][0]["type"] == "control"
        assert report["steps"][1]["type"] == "system_prompt"
        assert report["steps"][2]["type"] == "system_prompt"

        # 2 divergence entries (one per perturbation)
        assert len(report["divergence"]) == 2

        # Divergence metrics should show the pirate response differs more
        pirate_div = report["divergence"][0]
        concise_div = report["divergence"][1]
        assert pirate_div["word_diff_ratio"] > 0
        assert concise_div["word_diff_ratio"] > 0

    async def test_streaming_sse_sequence(self, api_client):
        """Streaming experiment yields correct SSE event sequence."""
        client, _ = api_client
        conv = await _create_conversation(client)

        resp = await client.post(
            f"/api/rhizomes/{conv['rhizome_id']}/nodes/{conv['node_ids'][-1]}/perturb",
            json={
                "perturbations": [
                    {"type": "system_prompt", "system_prompt": "Be concise."},
                ],
                "provider": "perturb-provider",
                "include_control": True,
                "stream": True,
            },
        )
        assert resp.status_code == 200

        events = []
        for line in resp.text.split("\n"):
            line = line.strip()
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: ") and event_type:
                events.append({"type": event_type, "data": line[6:]})
                event_type = None

        event_types = [e["type"] for e in events]

        # Should contain: perturbation_step, text_delta(s), message_stop (for control),
        # then perturbation_step, text_delta(s), message_stop (for perturbation),
        # then perturbation_complete
        assert "perturbation_step" in event_types
        assert "text_delta" in event_types
        assert "message_stop" in event_types
        assert "perturbation_complete" in event_types

        # perturbation_step events should have step numbers
        step_events = [e for e in events if e["type"] == "perturbation_step"]
        assert len(step_events) == 2  # control + 1 perturbation

    async def test_report_persisted_and_retrievable(self, api_client):
        """Report created via POST is retrievable via GET."""
        client, _ = api_client
        conv = await _create_conversation(client)

        # Run experiment
        resp = await client.post(
            f"/api/rhizomes/{conv['rhizome_id']}/nodes/{conv['node_ids'][-1]}/perturb",
            json={
                "perturbations": [
                    {"type": "system_prompt", "system_prompt": "Be brief."},
                ],
                "provider": "perturb-provider",
                "include_control": True,
                "stream": False,
            },
        )
        assert resp.status_code == 200
        report = resp.json()
        report_id = report["report_id"]

        # List reports
        list_resp = await client.get(
            f"/api/rhizomes/{conv['rhizome_id']}/perturbation-reports"
        )
        assert list_resp.status_code == 200
        reports = list_resp.json()
        assert len(reports) == 1
        assert reports[0]["report_id"] == report_id

        # Get single report
        get_resp = await client.get(
            f"/api/rhizomes/{conv['rhizome_id']}/perturbation-reports/{report_id}"
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["report_id"] == report_id

    async def test_experiment_combines_with_existing_exclusions(self, api_client):
        """Perturbation exclusions combine with pre-existing rhizome exclusions."""
        client, extras = api_client
        conv = await _create_conversation(client)

        # Pre-exclude the second node
        node_to_exclude = conv["node_ids"][1]
        scope_node = conv["node_ids"][-1]
        await client.post(
            f"/api/rhizomes/{conv['rhizome_id']}/nodes/{node_to_exclude}/exclude",
            json={"scope_node_id": scope_node},
        )

        # Now run experiment that additionally excludes another node
        another_node = conv["node_ids"][2]
        resp = await client.post(
            f"/api/rhizomes/{conv['rhizome_id']}/nodes/{conv['node_ids'][-1]}/perturb",
            json={
                "perturbations": [
                    {"type": "node_exclusion", "node_id": another_node, "exclude": True},
                ],
                "provider": "perturb-provider",
                "include_control": True,
                "stream": False,
            },
        )
        assert resp.status_code == 200
        report = resp.json()

        # Both control and perturbation should have run successfully
        assert len(report["steps"]) == 2
        # The perturbation should have even fewer messages than control
        # (control already has node_to_exclude excluded, perturbation adds another_node)

    async def test_experiment_without_control(self, api_client):
        """Experiment with include_control=false skips the baseline."""
        client, _ = api_client
        conv = await _create_conversation(client)

        resp = await client.post(
            f"/api/rhizomes/{conv['rhizome_id']}/nodes/{conv['node_ids'][-1]}/perturb",
            json={
                "perturbations": [
                    {"type": "system_prompt", "system_prompt": "Be a pirate."},
                ],
                "provider": "perturb-provider",
                "include_control": False,
                "stream": False,
            },
        )
        assert resp.status_code == 200
        report = resp.json()

        # Only 1 step (no control)
        assert len(report["steps"]) == 1
        assert report["steps"][0]["type"] == "system_prompt"
        # No divergence (need control to compare against)
        assert len(report["divergence"]) == 0
