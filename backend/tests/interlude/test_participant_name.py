"""User nodes can carry a participant name (e.g. a guest talking to Sun)."""


async def test_participant_name_is_recorded(client):
    rid = (await client.post("/api/rhizomes", json={"title": "t"})).json()["rhizome_id"]
    resp = await client.post(f"/api/rhizomes/{rid}/nodes", json={"content": "hi", "participant_name": "Alice"})
    assert resp.status_code == 201
    assert resp.json()["participant_name"] == "Alice"
    node = (await client.get(f"/api/rhizomes/{rid}")).json()["nodes"][0]
    assert node["participant_name"] == "Alice"


async def test_participant_name_defaults_to_none(client):
    rid = (await client.post("/api/rhizomes", json={"title": "t"})).json()["rhizome_id"]
    resp = await client.post(f"/api/rhizomes/{rid}/nodes", json={"content": "hi"})
    assert resp.json()["participant_name"] is None
