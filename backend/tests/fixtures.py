"""Shared test helpers. Grows with each subphase."""

from datetime import UTC, datetime
from uuid import uuid4

from httpx import AsyncClient

from qivis.models import (
    EventEnvelope,
    NodeCreatedPayload,
    SamplingParams,
    TreeCreatedPayload,
)


def make_tree_created_envelope(
    tree_id: str | None = None,
    title: str = "Test Tree",
    default_model: str | None = "claude-sonnet-4-5-20250929",
    default_provider: str | None = "anthropic",
    default_system_prompt: str | None = "You are helpful.",
    **payload_overrides: object,
) -> EventEnvelope:
    """Create a TreeCreated EventEnvelope for testing."""
    tree_id = tree_id or str(uuid4())
    payload = TreeCreatedPayload(
        title=title,
        default_model=default_model,
        default_provider=default_provider,
        default_system_prompt=default_system_prompt,
        **payload_overrides,
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="TreeCreated",
        payload=payload.model_dump(),
    )


def make_node_created_envelope(
    tree_id: str,
    node_id: str | None = None,
    parent_id: str | None = None,
    role: str = "user",
    content: str = "Hello",
    **payload_overrides: object,
) -> EventEnvelope:
    """Create a NodeCreated EventEnvelope for testing."""
    node_id = node_id or str(uuid4())
    payload = NodeCreatedPayload(
        node_id=node_id,
        parent_id=parent_id,
        role=role,
        content=content,
        **payload_overrides,
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="NodeCreated",
        payload=payload.model_dump(),
    )


def make_full_node_created_envelope(tree_id: str, parent_id: str | None = None) -> EventEnvelope:
    """Create a NodeCreated envelope with all generation fields populated."""
    from qivis.models import ContextUsage, LogprobData

    node_id = str(uuid4())
    payload = NodeCreatedPayload(
        node_id=node_id,
        generation_id=str(uuid4()),
        parent_id=parent_id,
        role="assistant",
        content="Hello! How can I help you?",
        model="claude-sonnet-4-5-20250929",
        provider="anthropic",
        system_prompt="You are helpful.",
        sampling_params=SamplingParams(temperature=0.7),
        mode="chat",
        usage={"input_tokens": 25, "output_tokens": 10},
        latency_ms=450,
        finish_reason="end_turn",
        logprobs=LogprobData(
            tokens=[], provider_format="anthropic", top_k_available=0
        ),
        context_usage=ContextUsage(
            total_tokens=35, max_tokens=200000,
            breakdown={"system": 10, "user": 15, "assistant": 10},
            excluded_tokens=0, excluded_count=0,
        ),
        participant_id=None,
        participant_name=None,
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="NodeCreated",
        payload=payload.model_dump(),
    )


# -- API-level helpers (available from Phase 0.3 onward) --


async def create_test_tree(
    client: AsyncClient,
    title: str = "Test Tree",
    system_prompt: str = "You are helpful.",
) -> dict:
    """Create a tree via the API and return the response JSON."""
    resp = await client.post("/api/trees", json={
        "title": title,
        "default_system_prompt": system_prompt,
    })
    assert resp.status_code == 201
    return resp.json()
