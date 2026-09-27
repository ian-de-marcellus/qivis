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
