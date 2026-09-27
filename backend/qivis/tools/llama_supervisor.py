"""On-demand llama.cpp server: start a model when someone talks to it,
stop it after a stretch of silence. Serves one model or several.

Sits on the port Qivis already uses for llama.cpp (LLAMACPP_BASE_URL) and
proxies to a real llama-server it launches on a private port. Nothing in
Qivis needs to change:

- The first real request (e.g. /completion) starts llama-server and waits
  for it to finish loading; the request is then passed through, streaming
  included.
- After `--idle` seconds with no requests in flight, llama-server is
  stopped, freeing its memory. The next request starts it again.
- /props is answered from memory while the model sleeps (the last real
  /props, or a minimal one naming the model file), so Qivis starting up
  or listing models doesn't wake it. /health reports the supervisor as up.

Several models: repeat --model. Each gets its own llama-server (on
consecutive private ports, started and stopped independently); a request goes
to the model it names -- the "model" field of a JSON body or ?model= -- by
file name, and to the first model when it names none.

    uv run python -m qivis.tools.llama_supervisor \\
        --model ~/Models/Sun-v1.0.1-8B.Q4_K_M.gguf \\
        --model ~/Models/olmo3/Olmo-3-7B-stage1-step1413814.BF16.gguf \\
        --port 8080 --idle 3600 -- -ngl 99 -c 8192
"""

import argparse
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

logger = logging.getLogger("llama_supervisor")
HOP_HEADERS = {"content-length", "transfer-encoding", "connection", "keep-alive", "host"}


class Supervisor:
    def __init__(
        self,
        model: Path,
        backend_port: int,
        idle_seconds: float,
        llama_cmd: list[str],
        extra_args: list[str],
        startup_timeout: float = 300.0,
        log_path: Path | None = None,
    ):
        self.model = model
        self.backend = f"http://127.0.0.1:{backend_port}"
        self.backend_port = backend_port
        self.idle_seconds = idle_seconds
        self.llama_cmd = llama_cmd
        self.extra_args = extra_args
        self.startup_timeout = startup_timeout
        self.log_path = log_path
        self.proc: asyncio.subprocess.Process | None = None
        self.in_flight = 0
        self.last_activity = time.monotonic()
        self.cached_props: dict | None = None
        self._lock = asyncio.Lock()
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(600, connect=5))

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def placeholder_props(self) -> dict:
        settings: dict = {}
        for flag in ("-c", "--ctx-size"):
            if flag in self.extra_args:
                i = self.extra_args.index(flag)
                if i + 1 < len(self.extra_args) and self.extra_args[i + 1].isdigit():
                    settings["n_ctx"] = int(self.extra_args[i + 1])
        return {
            "model_alias": self.model.name,
            "model_path": str(self.model),
            "default_generation_settings": settings,
            "supervisor": "sleeping",
        }

    async def ensure_running(self) -> None:
        async with self._lock:
            if self.running:
                return
            logger.info("waking: starting llama-server for %s", self.model.name)
            log = open(self.log_path, "ab") if self.log_path else asyncio.subprocess.DEVNULL
            self.proc = await asyncio.create_subprocess_exec(
                *self.llama_cmd,
                "-m",
                str(self.model),
                "--host",
                "127.0.0.1",
                "--port",
                str(self.backend_port),
                *self.extra_args,
                stdout=log,
                stderr=log,
            )
            if not isinstance(log, int):
                log.close()  # the child has its own copy
            deadline = time.monotonic() + self.startup_timeout
            while time.monotonic() < deadline:
                if self.proc.returncode is not None:
                    raise RuntimeError(f"llama-server exited with {self.proc.returncode}")
                try:
                    r = await self.client.get(f"{self.backend}/health", timeout=2)
                    if r.status_code == 200:
                        logger.info("llama-server ready")
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.5)
            await self.stop()
            raise RuntimeError("llama-server did not become ready in time")

    async def stop(self) -> None:
        if self.proc is None:
            return
        if self.proc.returncode is None:
            logger.info(
                "sleeping: stopping llama-server after %.0fs idle",
                time.monotonic() - self.last_activity,
            )
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=15)
            except TimeoutError:
                self.proc.kill()
                await self.proc.wait()
        self.proc = None

    async def maybe_sleep(self) -> bool:
        """Stop the model if it has been idle long enough. Returns True if stopped."""
        if (
            self.running
            and self.in_flight == 0
            and time.monotonic() - self.last_activity > self.idle_seconds
        ):
            async with self._lock:
                if self.in_flight == 0 and self.running:
                    await self.stop()
                    return True
        return False

    async def idle_watch(self, interval: float = 30.0) -> None:
        while True:
            await asyncio.sleep(interval)
            await self.maybe_sleep()


class Pool:
    """Several supervised models behind one port; requests pick by model file name."""

    def __init__(self, models: list[Supervisor]):
        if not models:
            raise ValueError("at least one model")
        self.models = models

    def pick(self, name: str | None) -> Supervisor:
        if name:
            base = name.rsplit("/", 1)[-1]
            for sup in self.models:
                if sup.model.name == base:
                    return sup
        return self.models[0]


class _ReleasingStream(StreamingResponse):
    """A streamed response that runs `release` once it's over, however it ends.

    A client that disconnects early can leave the body iterator unfinished (or
    never started), so cleanup can't live in the iterator: a leaked in-flight
    count would keep the model awake forever.
    """

    def __init__(self, content, release, **kwargs):
        super().__init__(content, **kwargs)
        self._release = release

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._release()


def create_app(sup: Supervisor | Pool, idle_check_interval: float = 30.0) -> FastAPI:
    pool = sup if isinstance(sup, Pool) else Pool([sup])

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        watches = [asyncio.create_task(m.idle_watch(idle_check_interval)) for m in pool.models]
        yield
        for w in watches:
            w.cancel()
        for m in pool.models:
            await m.stop()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    def slot_status(m: Supervisor) -> dict:
        return {
            "model": m.model.name,
            "running": m.running,
            "in_flight": m.in_flight,
            "idle_for": round(time.monotonic() - m.last_activity, 1),
            "idle_limit": m.idle_seconds,
        }

    @app.get("/supervisor/status")
    async def status():
        # The first model's status at the top level (as before), all of them under "models"
        return {**slot_status(pool.models[0]), "models": [slot_status(m) for m in pool.models]}

    @app.get("/supervisor/models")
    async def models():
        return [m.model.name for m in pool.models]

    @app.get("/health")
    async def health(model: str | None = None):
        return {"status": "ok", "model": "running" if pool.pick(model).running else "sleeping"}

    @app.get("/props")
    async def props(model: str | None = None):
        m = pool.pick(model)
        if not m.running:
            return JSONResponse(m.cached_props or m.placeholder_props())
        r = await m.client.get(f"{m.backend}/props")
        if r.status_code == 200:
            m.cached_props = r.json()
        return Response(r.content, status_code=r.status_code, media_type="application/json")

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
    async def proxy(path: str, request: Request):
        body = await request.body()
        m = pool.pick(request.query_params.get("model") or _named_model(body))
        m.in_flight += 1
        m.last_activity = time.monotonic()
        try:
            await m.ensure_running()
            headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}
            upstream = m.client.build_request(
                request.method,
                f"{m.backend}/{path}",
                params=request.query_params,
                headers=headers,
                content=body,
            )
            resp = await m.client.send(upstream, stream=True)
        except Exception as e:
            m.in_flight -= 1
            m.last_activity = time.monotonic()
            logger.exception("proxy failed")
            return JSONResponse(
                {"error": {"code": 503, "message": f"model server unavailable: {e}"}},
                status_code=503,
            )

        async def release() -> None:
            m.in_flight -= 1
            m.last_activity = time.monotonic()
            await resp.aclose()

        out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in HOP_HEADERS}
        return _ReleasingStream(
            resp.aiter_raw(), release, status_code=resp.status_code, headers=out_headers,
        )

    return app


def _named_model(body: bytes) -> str | None:
    """The model a JSON request body names, if any."""
    if not body or not body.lstrip().startswith(b"{"):
        return None
    try:
        name = json.loads(body).get("model")
    except (ValueError, AttributeError):
        return None
    return name if isinstance(name, str) else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--model", required=True, type=Path, action="append",
        help="a GGUF to serve (repeat for several; the first is the default)",
    )
    parser.add_argument("--port", type=int, default=8080, help="port Qivis talks to")
    parser.add_argument(
        "--backend-port", type=int, default=8181,
        help="first private llama-server port (one per model, consecutive)",
    )
    parser.add_argument(
        "--idle", type=float, default=3600, help="seconds of silence before sleeping"
    )
    parser.add_argument("--llama-server", default="llama-server", help="llama-server binary")
    parser.add_argument("--log", type=Path, default=None, help="append llama-server output here")
    parser.add_argument("llama_args", nargs="*", help="extra llama-server args (after --)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    pool = Pool([
        Supervisor(
            model=path.expanduser(),
            backend_port=args.backend_port + i,
            idle_seconds=args.idle,
            llama_cmd=[args.llama_server],
            extra_args=args.llama_args,
            log_path=args.log,
        )
        for i, path in enumerate(args.model)
    ])
    import uvicorn

    uvicorn.run(create_app(pool), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
