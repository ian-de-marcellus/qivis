"""Shared test helpers. Grows with each subphase."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from httpx import AsyncClient

from qivis.models import (
    AnnotationAddedPayload,
    AnnotationRemovedPayload,
    BookmarkCreatedPayload,
    BookmarkRemovedPayload,
    BookmarkSummaryGeneratedPayload,
    DigressionGroupCreatedPayload,
    DigressionGroupToggledPayload,
    EventEnvelope,
    NoteAddedPayload,
    NoteRemovedPayload,
    NodeAnchoredPayload,
    NodeContentEditedPayload,
    NodeContextExcludedPayload,
    NodeContextIncludedPayload,
    NodeCreatedPayload,
    NodeUnanchoredPayload,
    SamplingParams,
    SummaryGeneratedPayload,
    SummaryRemovedPayload,
    TreeArchivedPayload,
    TreeCreatedPayload,
    TreeMetadataUpdatedPayload,
    TreeUnarchivedPayload,
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


def make_node_content_edited_envelope(
    tree_id: str,
    node_id: str,
    original_content: str,
    new_content: str | None,
) -> EventEnvelope:
    """Create a NodeContentEdited EventEnvelope for testing."""
    payload = NodeContentEditedPayload(
        node_id=node_id,
        original_content=original_content,
        new_content=new_content,
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="NodeContentEdited",
        payload=payload.model_dump(),
    )


def make_tree_metadata_updated_envelope(
    tree_id: str,
    field: str,
    old_value: Any = None,
    new_value: Any = None,
) -> EventEnvelope:
    """Create a TreeMetadataUpdated EventEnvelope for testing."""
    payload = TreeMetadataUpdatedPayload(
        field=field,
        old_value=old_value,
        new_value=new_value,
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="TreeMetadataUpdated",
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


def make_annotation_added_envelope(
    tree_id: str,
    node_id: str,
    tag: str,
    annotation_id: str | None = None,
    value: Any = None,
    notes: str | None = None,
) -> EventEnvelope:
    """Create an AnnotationAdded EventEnvelope for testing."""
    annotation_id = annotation_id or str(uuid4())
    payload = AnnotationAddedPayload(
        annotation_id=annotation_id,
        node_id=node_id,
        tag=tag,
        value=value,
        notes=notes,
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="AnnotationAdded",
        payload=payload.model_dump(),
    )


def make_annotation_removed_envelope(
    tree_id: str,
    annotation_id: str,
    reason: str | None = None,
) -> EventEnvelope:
    """Create an AnnotationRemoved EventEnvelope for testing."""
    payload = AnnotationRemovedPayload(
        annotation_id=annotation_id,
        reason=reason,
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="AnnotationRemoved",
        payload=payload.model_dump(),
    )


def make_bookmark_created_envelope(
    tree_id: str,
    node_id: str,
    label: str = "Bookmark",
    bookmark_id: str | None = None,
    notes: str | None = None,
) -> EventEnvelope:
    """Create a BookmarkCreated EventEnvelope for testing."""
    bookmark_id = bookmark_id or str(uuid4())
    payload = BookmarkCreatedPayload(
        bookmark_id=bookmark_id,
        node_id=node_id,
        label=label,
        notes=notes,
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="BookmarkCreated",
        payload=payload.model_dump(),
    )


def make_bookmark_removed_envelope(
    tree_id: str,
    bookmark_id: str,
) -> EventEnvelope:
    """Create a BookmarkRemoved EventEnvelope for testing."""
    payload = BookmarkRemovedPayload(
        bookmark_id=bookmark_id,
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="BookmarkRemoved",
        payload=payload.model_dump(),
    )


def make_bookmark_summary_generated_envelope(
    tree_id: str,
    bookmark_id: str,
    summary: str = "A concise summary of the branch.",
    model: str = "claude-haiku-4-5",
    summarized_node_ids: list[str] | None = None,
) -> EventEnvelope:
    """Create a BookmarkSummaryGenerated EventEnvelope for testing."""
    payload = BookmarkSummaryGeneratedPayload(
        bookmark_id=bookmark_id,
        summary=summary,
        model=model,
        summarized_node_ids=summarized_node_ids or [],
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="BookmarkSummaryGenerated",
        payload=payload.model_dump(),
    )


def make_node_context_excluded_envelope(
    tree_id: str,
    node_id: str,
    scope_node_id: str,
    reason: str | None = None,
) -> EventEnvelope:
    """Create a NodeContextExcluded EventEnvelope for testing."""
    payload = NodeContextExcludedPayload(
        node_id=node_id,
        scope_node_id=scope_node_id,
        reason=reason,
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="NodeContextExcluded",
        payload=payload.model_dump(),
    )


def make_node_context_included_envelope(
    tree_id: str,
    node_id: str,
    scope_node_id: str,
) -> EventEnvelope:
    """Create a NodeContextIncluded EventEnvelope for testing."""
    payload = NodeContextIncludedPayload(
        node_id=node_id,
        scope_node_id=scope_node_id,
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="NodeContextIncluded",
        payload=payload.model_dump(),
    )


def make_digression_group_created_envelope(
    tree_id: str,
    group_id: str | None = None,
    node_ids: list[str] | None = None,
    label: str = "Digression",
    excluded_by_default: bool = False,
) -> EventEnvelope:
    """Create a DigressionGroupCreated EventEnvelope for testing."""
    group_id = group_id or str(uuid4())
    payload = DigressionGroupCreatedPayload(
        group_id=group_id,
        node_ids=node_ids or [],
        label=label,
        excluded_by_default=excluded_by_default,
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="DigressionGroupCreated",
        payload=payload.model_dump(),
    )


def make_digression_group_toggled_envelope(
    tree_id: str,
    group_id: str,
    included: bool,
) -> EventEnvelope:
    """Create a DigressionGroupToggled EventEnvelope for testing."""
    payload = DigressionGroupToggledPayload(
        group_id=group_id,
        included=included,
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="DigressionGroupToggled",
        payload=payload.model_dump(),
    )


def make_node_anchored_envelope(
    tree_id: str,
    node_id: str,
) -> EventEnvelope:
    """Create a NodeAnchored EventEnvelope for testing."""
    payload = NodeAnchoredPayload(node_id=node_id)
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="NodeAnchored",
        payload=payload.model_dump(),
    )


def make_node_unanchored_envelope(
    tree_id: str,
    node_id: str,
) -> EventEnvelope:
    """Create a NodeUnanchored EventEnvelope for testing."""
    payload = NodeUnanchoredPayload(node_id=node_id)
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="NodeUnanchored",
        payload=payload.model_dump(),
    )


def make_note_added_envelope(
    tree_id: str,
    node_id: str,
    content: str = "A research note.",
    note_id: str | None = None,
) -> EventEnvelope:
    """Create a NoteAdded EventEnvelope for testing."""
    note_id = note_id or str(uuid4())
    payload = NoteAddedPayload(
        note_id=note_id,
        node_id=node_id,
        content=content,
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="NoteAdded",
        payload=payload.model_dump(),
    )


def make_note_removed_envelope(
    tree_id: str,
    note_id: str,
    reason: str | None = None,
) -> EventEnvelope:
    """Create a NoteRemoved EventEnvelope for testing."""
    payload = NoteRemovedPayload(
        note_id=note_id,
        reason=reason,
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="NoteRemoved",
        payload=payload.model_dump(),
    )


def make_summary_generated_envelope(
    tree_id: str,
    anchor_node_id: str,
    scope: str = "branch",
    summary_type: str = "concise",
    summary: str = "A test summary of the conversation.",
    model: str = "claude-haiku-4-5-20251001",
    node_ids: list[str] | None = None,
    prompt_used: str | None = None,
    summary_id: str | None = None,
) -> EventEnvelope:
    """Create a SummaryGenerated EventEnvelope for testing."""
    summary_id = summary_id or str(uuid4())
    payload = SummaryGeneratedPayload(
        summary_id=summary_id,
        anchor_node_id=anchor_node_id,
        scope=scope,
        node_ids=node_ids or [anchor_node_id],
        summary=summary,
        model=model,
        summary_type=summary_type,
        prompt_used=prompt_used,
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="SummaryGenerated",
        payload=payload.model_dump(),
    )


def make_summary_removed_envelope(
    tree_id: str,
    summary_id: str,
    reason: str | None = None,
) -> EventEnvelope:
    """Create a SummaryRemoved EventEnvelope for testing."""
    payload = SummaryRemovedPayload(
        summary_id=summary_id,
        reason=reason,
    )
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="SummaryRemoved",
        payload=payload.model_dump(),
    )


def make_tree_archived_envelope(
    tree_id: str,
    reason: str | None = None,
) -> EventEnvelope:
    """Create a TreeArchived EventEnvelope for testing."""
    payload = TreeArchivedPayload(reason=reason)
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="TreeArchived",
        payload=payload.model_dump(),
    )


def make_tree_unarchived_envelope(
    tree_id: str,
) -> EventEnvelope:
    """Create a TreeUnarchived EventEnvelope for testing."""
    payload = TreeUnarchivedPayload()
    return EventEnvelope(
        event_id=str(uuid4()),
        tree_id=tree_id,
        timestamp=datetime.now(UTC),
        device_id="test",
        event_type="TreeUnarchived",
        payload=payload.model_dump(),
    )


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
