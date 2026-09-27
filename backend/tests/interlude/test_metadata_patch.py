"""Rhizome metadata: set on create, merged on patch.

Clients used to create a rhizome, then PATCH its metadata, and change one tag
by fetching the whole rhizome, merging, and writing every key back (two
clients doing that at once lost one's change). Now create takes metadata,
and PATCH merges by top-level key: a value replaces, null removes.
"""

import asyncio


async def _meta(client, rid: str) -> dict:
    return (await client.get(f"/api/rhizomes/{rid}")).json()["metadata"]


async def test_create_with_metadata(client):
    r = await client.post("/api/rhizomes", json={
        "title": "t", "metadata": {"tags": ["a"], "generation_mode": "completion", "gone": None},
    })
    assert r.status_code == 201
    assert await _meta(client, r.json()["rhizome_id"]) == {
        "tags": ["a"], "generation_mode": "completion"}


async def test_patch_merges_and_null_removes(client):
    rid = (await client.post("/api/rhizomes", json={
        "title": "t", "metadata": {"tags": ["a"], "stream_responses": True},
    })).json()["rhizome_id"]
    await client.patch(f"/api/rhizomes/{rid}", json={"metadata": {"folders": ["F"]}})
    assert await _meta(client, rid) == {"tags": ["a"], "stream_responses": True, "folders": ["F"]}
    await client.patch(f"/api/rhizomes/{rid}", json={"metadata": {"stream_responses": None}})
    assert await _meta(client, rid) == {"tags": ["a"], "folders": ["F"]}


async def test_concurrent_patches_keep_both_changes(client):
    rid = (await client.post("/api/rhizomes", json={"title": "t"})).json()["rhizome_id"]
    await asyncio.gather(*[
        client.patch(f"/api/rhizomes/{rid}", json={"metadata": {f"k{i}": i}}) for i in range(5)
    ])
    assert await _meta(client, rid) == {f"k{i}": i for i in range(5)}
