"""On-demand llama.cpp supervisor: sleeps until needed, proxies, sleeps again."""

import socket
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from qivis.tools.llama_supervisor import Supervisor, create_app

STUB = Path(__file__).parent / "stub_llama.py"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def sup_client():
    sup = Supervisor(
        model=Path("/models/sun-1.0.1.gguf"),
        backend_port=free_port(),
        idle_seconds=3600,
        llama_cmd=[sys.executable, str(STUB)],
        extra_args=["-ngl", "99"],
        startup_timeout=20,
    )
    async with AsyncClient(
        transport=ASGITransport(app=create_app(sup)), base_url="http://sup"
    ) as c:
        yield sup, c
    await sup.stop()


async def test_starts_asleep_and_props_do_not_wake_it(sup_client):
    sup, c = sup_client
    assert (await c.get("/health")).json() == {"status": "ok", "model": "sleeping"}
    props = (await c.get("/props")).json()
    assert props["model_alias"] == "sun-1.0.1.gguf"  # named after the model file
    assert not sup.running


async def test_first_real_request_wakes_and_proxies(sup_client):
    sup, c = sup_client
    r = await c.post("/completion", json={"prompt": "hi"})
    assert r.status_code == 200 and r.json()["echo"] == "hi"
    assert sup.running
    # while awake, /props is the real one, and gets remembered for sleep
    assert (await c.get("/props")).json()["real"] is True
    await sup.stop()
    assert (await c.get("/props")).json()["real"] is True


async def test_streaming_passes_through(sup_client):
    sup, c = sup_client
    async with c.stream("POST", "/completion", json={"prompt": "hi", "stream": True}) as r:
        text = "".join([chunk async for chunk in r.aiter_text()])
    assert '"Hel"' in text and '"lo"' in text and '"stop": true' in text
    assert sup.in_flight == 0


async def test_sleeps_after_idle_and_wakes_again(sup_client):
    sup, c = sup_client
    await c.post("/completion", json={"prompt": "hi"})
    assert not await sup.maybe_sleep()  # not idle long enough
    sup.idle_seconds = 0
    assert await sup.maybe_sleep()  # now it sleeps
    assert not sup.running
    r = await c.post("/completion", json={"prompt": "again"})
    assert r.json()["echo"] == "again" and sup.running


async def test_does_not_sleep_mid_request(sup_client):
    sup, c = sup_client
    await c.post("/completion", json={"prompt": "hi"})
    sup.idle_seconds, sup.in_flight = 0, 1  # a request is still streaming
    assert not await sup.maybe_sleep()
    assert sup.running
    sup.in_flight = 0


async def test_unavailable_model_is_a_clean_503():
    sup = Supervisor(
        model=Path("/m.gguf"),
        backend_port=free_port(),
        idle_seconds=60,
        llama_cmd=[sys.executable, "-c", "raise SystemExit(3)"],
        extra_args=[],
        startup_timeout=5,
    )
    async with AsyncClient(
        transport=ASGITransport(app=create_app(sup)), base_url="http://sup"
    ) as c:
        r = await c.post("/completion", json={"prompt": "hi"})
    assert r.status_code == 503 and "unavailable" in r.json()["error"]["message"]
    assert sup.in_flight == 0


async def test_client_gone_before_the_body_still_releases(sup_client):
    """A disconnect before any body is read must not leave the model awake forever."""
    sup, c = sup_client
    app = create_app(sup)
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1", "method": "POST", "scheme": "http", "path": "/completion",
        "raw_path": b"/completion", "query_string": b"", "root_path": "",
        "headers": [(b"content-type", b"application/json")], "server": ("sup", 80),
        "client": ("127.0.0.1", 1),
    }
    sent_body = False

    async def receive():
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": b'{"prompt": "hi"}', "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            raise OSError("client went away")

    with pytest.raises(Exception):
        await app(scope, receive, send)
    assert sup.in_flight == 0


async def test_several_models_route_by_name_and_wake_separately():
    from qivis.tools.llama_supervisor import Pool

    base = free_port()
    sun, olmo = (
        Supervisor(
            model=Path(f"/models/{name}"), backend_port=port, idle_seconds=3600,
            llama_cmd=[sys.executable, str(STUB)], extra_args=[], startup_timeout=20,
        )
        for name, port in (("sun.gguf", base), ("olmo.gguf", free_port()))
    )
    async with AsyncClient(
        transport=ASGITransport(app=create_app(Pool([sun, olmo]))), base_url="http://sup"
    ) as c:
        assert (await c.get("/supervisor/models")).json() == ["sun.gguf", "olmo.gguf"]
        # Asking about a model doesn't wake it
        assert (await c.get("/props", params={"model": "olmo.gguf"})).json()["model_alias"] == "olmo.gguf"
        # A request naming a model (by file name or path) goes to it, and only it wakes
        r = await c.post("/completion", json={"model": "/anywhere/olmo.gguf", "prompt": "hi"})
        assert r.json()["echo"] == "hi"
        assert olmo.running and not sun.running
        # Naming nothing goes to the first model
        await c.post("/completion", json={"prompt": "hey"})
        assert sun.running
        status = (await c.get("/supervisor/status")).json()
        assert [m["model"] for m in status["models"]] == ["sun.gguf", "olmo.gguf"]
    await sun.stop()
    await olmo.stop()


async def test_memory_budget_stops_idle_models_to_make_room(tmp_path):
    """On a laptop: small models share memory; a big one gets it to itself."""
    from qivis.tools.llama_supervisor import Pool

    def model(name: str, gb: int) -> Supervisor:
        path = tmp_path / name
        with open(path, "wb") as f:
            f.truncate(gb * 1024**3)  # sparse: the size without the disk space
        return Supervisor(
            model=path, backend_port=free_port(), idle_seconds=3600,
            llama_cmd=[sys.executable, str(STUB)], extra_args=[], startup_timeout=20,
        )

    sun, olmo, big = model("sun.gguf", 5), model("olmo.gguf", 15), model("big.gguf", 34)
    pool = Pool([sun, olmo, big], memory_budget=36 * 1024**3)
    async with AsyncClient(
        transport=ASGITransport(app=create_app(pool)), base_url="http://sup"
    ) as c:
        await c.post("/completion", json={"model": "sun.gguf", "prompt": "a"})
        await c.post("/completion", json={"model": "olmo.gguf", "prompt": "b"})
        assert sun.running and olmo.running  # 20 GB: both fit
        await c.post("/completion", json={"model": "big.gguf", "prompt": "c"})
        assert big.running and not sun.running and not olmo.running
        await c.post("/completion", json={"model": "sun.gguf", "prompt": "d"})
        assert sun.running and not big.running  # 39 GB would be over
    for m in (sun, olmo, big):
        await m.stop()
