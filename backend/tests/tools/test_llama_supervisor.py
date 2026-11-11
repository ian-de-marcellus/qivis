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


async def test_models_woken_at_once_still_fit_the_budget(tmp_path):
    """Two requests for different models at the same moment: the second waits and makes room."""
    import asyncio

    from qivis.tools.llama_supervisor import Pool

    def model(name: str, gb: int) -> Supervisor:
        path = tmp_path / name
        with open(path, "wb") as f:
            f.truncate(gb * 1024**3)
        return Supervisor(
            model=path, backend_port=free_port(), idle_seconds=3600,
            llama_cmd=[sys.executable, str(STUB)], extra_args=[], startup_timeout=20,
        )

    sun, big = model("sun.gguf", 5), model("big.gguf", 34)
    pool = Pool([sun, big], memory_budget=36 * 1024**3)
    async with AsyncClient(
        transport=ASGITransport(app=create_app(pool)), base_url="http://sup"
    ) as c:
        await asyncio.gather(
            c.post("/completion", json={"model": "sun.gguf", "prompt": "a"}),
            c.post("/completion", json={"model": "big.gguf", "prompt": "b"}),
        )
        assert not (sun.running and big.running)
    for m in (sun, big):
        await m.stop()


async def test_props_while_loading_say_what_is_known(sup_client):
    """A model still loading can't answer /props; the supervisor answers with its name."""

    class Launched:
        returncode = None

    sup, c = sup_client
    sup.proc = Launched()  # type: ignore[assignment]  # launched, not yet ready
    r = await c.get("/props")
    assert r.status_code == 200 and r.json()["model_alias"] == "sun-1.0.1.gguf"
    sup.proc = None


async def test_a_lease_makes_room_and_counts_until_released(tmp_path):
    """Another process (direct lookups) borrows GPU memory: idle models make room,
    and a model that won't fit beside the lease is refused at once, not squeezed in."""
    from qivis.tools.llama_supervisor import Pool

    def model(name: str, gb: int) -> Supervisor:
        path = tmp_path / name
        with open(path, "wb") as f:
            f.truncate(gb * 1024**3)
        return Supervisor(
            model=path, backend_port=free_port(), idle_seconds=3600,
            llama_cmd=[sys.executable, str(STUB)], extra_args=[], startup_timeout=20,
        )

    sun, olmo = model("sun.gguf", 5), model("olmo.gguf", 15)
    pool = Pool([sun, olmo], memory_budget=36 * 1024**3)
    async with AsyncClient(
        transport=ASGITransport(app=create_app(pool)), base_url="http://sup"
    ) as c:
        await c.post("/completion", json={"model": "olmo.gguf", "prompt": "a"})
        r = await c.post("/supervisor/lease", json={"name": "direct", "bytes": 34 * 1024**3, "ttl": 60})
        assert r.status_code == 200 and not olmo.running  # stopped to make room
        r = await c.post("/completion", json={"model": "sun.gguf", "prompt": "b"})
        assert r.status_code == 503 and "leased" in r.text and not sun.running
        assert (await c.get("/supervisor/status")).json()["leases"] == {"direct": 34 * 1024**3}
        await c.delete("/supervisor/lease", params={"name": "direct"})
        r = await c.post("/completion", json={"model": "sun.gguf", "prompt": "c"})
        assert r.status_code == 200 and sun.running
    for m in (sun, olmo):
        await m.stop()


async def test_a_lease_not_renewed_lapses(tmp_path):
    import asyncio

    from qivis.tools.llama_supervisor import Pool

    path = tmp_path / "sun.gguf"
    with open(path, "wb") as f:
        f.truncate(5 * 1024**3)
    sun = Supervisor(model=path, backend_port=free_port(), idle_seconds=3600,
                     llama_cmd=[sys.executable, str(STUB)], extra_args=[], startup_timeout=20)
    pool = Pool([sun], memory_budget=36 * 1024**3)
    await pool.lease("direct", 34 * 1024**3, ttl=0.2)
    assert pool.leased() > 0
    await asyncio.sleep(0.3)
    assert pool.leased() == 0


async def test_a_model_counts_its_working_memory_not_just_its_file(tmp_path, monkeypatch):
    """llama-server holds a context cache and buffers beyond the mapped weights: the
    budget counts them, estimated until the running server has been measured."""
    import qivis.tools.llama_supervisor as supervisor
    from qivis.tools.llama_supervisor import Pool

    def model(name: str, gb: int) -> Supervisor:
        path = tmp_path / name
        with open(path, "wb") as f:
            f.truncate(gb * 1024**3)
        return Supervisor(
            model=path, backend_port=free_port(), idle_seconds=3600,
            llama_cmd=[sys.executable, str(STUB)], extra_args=[], startup_timeout=20,
            overhead=4 * 1024**3,
        )

    a, b = model("a.gguf", 8), model("b.gguf", 8)
    assert a.size == 12 * 1024**3  # file + estimate, before it has run
    # Each running server measures 5 GB of its own memory
    monkeypatch.setattr(supervisor, "footprint", lambda pid: 5 * 1024**3)
    pool = Pool([a, b], memory_budget=24 * 1024**3)
    async with AsyncClient(
        transport=ASGITransport(app=create_app(pool)), base_url="http://sup"
    ) as c:
        await c.post("/completion", json={"model": "a.gguf", "prompt": "x"})
        assert a.size == 13 * 1024**3  # measured once up
        await c.post("/completion", json={"model": "b.gguf", "prompt": "y"})
        # Files alone (16 GB) would fit; with working memory (26 GB) they don't
        assert b.running and not a.running
        status = (await c.get("/supervisor/status")).json()
        b_status = next(m for m in status["models"] if m["model"] == "b.gguf")
        assert b_status["overhead_measured"] and b_status["file_size"] == 8 * 1024**3
    for m in (a, b):
        await m.stop()


def test_footprint_reads_a_real_process():
    import os

    from qivis.tools.llama_supervisor import footprint
    used = footprint(os.getpid())
    if sys.platform == "darwin":
        assert used is not None and used > 1024**2
    else:
        assert used is None


async def test_a_model_over_the_budget_alone_still_starts_with_the_rest_stopped(tmp_path):
    from qivis.tools.llama_supervisor import Pool

    def model(name: str, gb: int) -> Supervisor:
        path = tmp_path / name
        with open(path, "wb") as f:
            f.truncate(gb * 1024**3)
        return Supervisor(
            model=path, backend_port=free_port(), idle_seconds=3600,
            llama_cmd=[sys.executable, str(STUB)], extra_args=[], startup_timeout=20,
            overhead=4 * 1024**3,
        )

    small, big = model("small.gguf", 5), model("big.gguf", 34)  # 38 GB counted
    pool = Pool([small, big], memory_budget=36 * 1024**3)
    async with AsyncClient(
        transport=ASGITransport(app=create_app(pool)), base_url="http://sup"
    ) as c:
        await c.post("/completion", json={"model": "small.gguf", "prompt": "a"})
        await c.post("/completion", json={"model": "big.gguf", "prompt": "b"})
        assert big.running and not small.running
    for m in (small, big):
        await m.stop()
