"""Shared test helpers. Grows with each subphase."""

from datetime import UTC, datetime
from typing import Any, Literal
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
    **payload_overrides: Any,
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
    role: Literal["system", "user", "assistant", "tool", "researcher_note"] = "user",
    content: str = "Hello",
    **payload_overrides: Any,
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


async def create_tree_with_messages(
    client: AsyncClient,
    n_messages: int = 4,
    title: str = "Test Tree",
    system_prompt: str = "You are helpful.",
) -> dict:
    """Create a tree with N alternating user/assistant messages.

    Returns {"tree_id": str, "node_ids": [str, ...]} where node_ids
    are in creation order.
    """
    tree = await create_test_tree(client, title=title, system_prompt=system_prompt)
    tree_id = tree["tree_id"]
    node_ids: list[str] = []
    parent_id: str | None = None

    for i in range(n_messages):
        role = "user" if i % 2 == 0 else "assistant"
        body: dict = {"content": f"Message {i + 1}", "role": role}
        if parent_id is not None:
            body["parent_id"] = parent_id
        resp = await client.post(f"/api/trees/{tree_id}/nodes", json=body)
        assert resp.status_code == 201
        node = resp.json()
        node_ids.append(node["node_id"])
        parent_id = node["node_id"]

    return {"tree_id": tree_id, "node_ids": node_ids}


# -- Branching helpers (available from Phase 1.1 onward) --


async def create_branching_tree(client: AsyncClient) -> dict:
    """Create a tree with branches: root -> A -> B, root -> A -> C.

    B and C are siblings (both children of A).

    Returns {"tree_id": str, "node_ids": {"root": str, "A": str, "B": str, "C": str}}
    """
    tree = await create_test_tree(client, title="Branching Tree")
    tree_id = tree["tree_id"]

    root_resp = await client.post(f"/api/trees/{tree_id}/nodes", json={
        "content": "Root message",
    })
    assert root_resp.status_code == 201
    root_id = root_resp.json()["node_id"]

    a_resp = await client.post(f"/api/trees/{tree_id}/nodes", json={
        "content": "Message A",
        "role": "assistant",
        "parent_id": root_id,
    })
    assert a_resp.status_code == 201
    a_id = a_resp.json()["node_id"]

    b_resp = await client.post(f"/api/trees/{tree_id}/nodes", json={
        "content": "Message B (branch 1)",
        "parent_id": a_id,
    })
    assert b_resp.status_code == 201
    b_id = b_resp.json()["node_id"]

    c_resp = await client.post(f"/api/trees/{tree_id}/nodes", json={
        "content": "Message C (branch 2)",
        "parent_id": a_id,
    })
    assert c_resp.status_code == 201
    c_id = c_resp.json()["node_id"]

    return {
        "tree_id": tree_id,
        "node_ids": {"root": root_id, "A": a_id, "B": b_id, "C": c_id},
    }
