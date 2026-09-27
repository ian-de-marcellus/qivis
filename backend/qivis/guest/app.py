"""Guest portal server.

Run (localhost only; expose with `tailscale funnel 8100`):
    uv run uvicorn --factory qivis.guest.app:create_app --host 127.0.0.1 --port 8100

Every guest request is scoped to that guest: conversations are Qivis rhizomes
whose metadata names the guest, and anything else is a 404.
"""

import json
import logging
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from qivis.guest import auth
from qivis.guest.config import ConfigStore, Guest, GuestConfig, GuestModel, config_path

logger = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
NEED_INVITE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Invite needed</title><link rel="stylesheet" href="/app.css"></head><body><main class="gate">
<h1>You need an invite link</h1><p>This is a private space. If someone invited you, open the personal link they sent.</p>
</main></body></html>"""


class NewConversation(BaseModel):
    model_id: str


class NewMessage(BaseModel):
    content: str
    parent_id: str | None = None  # the displayed leaf; None for an empty conversation


class Regenerate(BaseModel):
    node_id: str  # the reply to try again


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _display_path(nodes: list[dict], choose: set[str]) -> list[tuple[dict, list[dict]]]:
    """Walk from the root, taking a chosen sibling where given, else the newest."""
    children: dict[str | None, list[dict]] = defaultdict(list)
    for n in nodes:
        children[n["parent_id"]].append(n)
    for sibs in children.values():
        sibs.sort(key=lambda n: n["created_at"])
    path, parent = [], None
    while children.get(parent):
        sibs = children[parent]
        pick = next((s for s in sibs if s["node_id"] in choose), sibs[-1])
        path.append((pick, sibs))
        parent = pick["node_id"]
    return path


def _guest_node(node: dict, siblings: list[dict], model_label: str) -> dict:
    content = node.get("edited_content") or node["content"]
    tokens = None
    lp = node.get("logprobs")
    if node["role"] == "assistant" and lp and lp.get("tokens"):
        toks = [
            {
                "t": t["token"],
                "p": round(t["linear_prob"], 4),
                "alts": [
                    {"t": a["token"], "p": round(a["linear_prob"], 4)}
                    for a in t["top_alternatives"][:5]
                ],
            }
            for t in lp["tokens"]
        ]
        if "".join(t["t"] for t in toks) == content:  # only when it aligns with the text
            tokens = toks
    return {
        "id": node["node_id"],
        "role": node["role"],
        "author": node.get("participant_name")
        or (model_label if node["role"] == "assistant" else "You"),
        "content": content,
        "tokens": tokens,
        "sibling_ids": [s["node_id"] for s in siblings],
        "created_at": node["created_at"],
    }


class RateLimiter:
    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, per_minute: int) -> bool:
        now, q = time.monotonic(), self._hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= per_minute:
            return False
        q.append(now)
        return True


def create_app(
    store: ConfigStore | None = None,
    qivis_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    store = store or ConfigStore(config_path())
    qivis = httpx.AsyncClient(
        base_url=store.get().qivis_url,
        transport=qivis_transport,
        timeout=httpx.Timeout(600, connect=10),
    )
    limiter = RateLimiter()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    # -- auth --

    def current(request: Request) -> tuple[GuestConfig, Guest]:
        cfg = store.get()
        guest_id = auth.verify(request.cookies.get(auth.COOKIE), cfg.session_secret)
        guest = cfg.guest(guest_id) if guest_id else None
        if guest is None:
            raise HTTPException(status_code=401, detail="Invite needed")
        return cfg, guest

    @app.get("/i/{token}")
    async def accept_invite(token: str):
        cfg = store.get()
        if not limiter.allow("invite", 30):
            raise HTTPException(status_code=429, detail="Too many attempts")
        h = auth.hash_token(token)
        guest = next((g for g in cfg.guests if g.token_sha256 == h and not g.revoked), None)
        if guest is None:
            return HTMLResponse(NEED_INVITE, status_code=404)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            auth.COOKIE,
            auth.sign(guest.id, cfg.session_secret),
            max_age=365 * 24 * 3600,
            httponly=True,
            secure=True,
            samesite="lax",
        )
        return response

    @app.get("/")
    async def index(request: Request):
        try:
            current(request)
        except HTTPException:
            return HTMLResponse(NEED_INVITE, status_code=401)
        return FileResponse(STATIC / "index.html")

    @app.get("/app.js")
    async def app_js():
        return FileResponse(STATIC / "app.js", media_type="text/javascript")

    @app.get("/app.css")
    async def app_css():
        return FileResponse(STATIC / "app.css", media_type="text/css")

    # -- helpers over Qivis --

    async def owned(rid: str, guest: Guest) -> dict:
        resp = await qivis.get(f"/api/rhizomes/{rid}")
        if resp.status_code != 200:
            raise HTTPException(status_code=404, detail="Not found")
        rhizome = resp.json()
        if (rhizome.get("metadata") or {}).get("guest", {}).get("id") != guest.id:
            raise HTTPException(status_code=404, detail="Not found")
        return rhizome

    def model_for(cfg: GuestConfig, rhizome: dict) -> GuestModel:
        model = cfg.model(rhizome["metadata"]["guest"].get("model_id", ""))
        if model is None:
            raise HTTPException(
                status_code=409, detail="This conversation's model is no longer available"
            )
        return model

    def check_rate(cfg: GuestConfig, guest: Guest) -> None:
        if not limiter.allow(f"msg:{guest.id}", cfg.limits.messages_per_minute):
            raise HTTPException(
                status_code=429, detail="Slow down a little: too many messages this minute"
            )

    async def relay(rid: str, parent_id: str, model: GuestModel, label: str) -> AsyncIterator[str]:
        body = {"provider": model.provider, "model": model.model, "stream": True}
        try:
            async with qivis.stream(
                "POST",
                f"/api/rhizomes/{rid}/nodes/{parent_id}/generate",
                json=body,
            ) as resp:
                if resp.status_code >= 300:
                    raise RuntimeError(f"Qivis returned {resp.status_code}")
                event = None
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data = json.loads(line[5:])
                        if event == "text_delta":
                            yield _sse("delta", {"text": data.get("text", "")})
                        elif event == "message_stop":
                            nodes = (await qivis.get(f"/api/rhizomes/{rid}")).json()["nodes"]
                            node = next(n for n in nodes if n["node_id"] == data["node_id"])
                            sibs = sorted(
                                (n for n in nodes if n["parent_id"] == node["parent_id"]),
                                key=lambda n: n["created_at"],
                            )
                            yield _sse("done", _guest_node(node, sibs, label))
                        elif event == "error":
                            raise RuntimeError(data.get("error"))
        except Exception:
            logger.exception("guest generation failed")
            yield _sse(
                "error", {"message": "Couldn't get a reply just now. Try again in a moment."}
            )

    # -- API --

    @app.get("/api/me")
    async def me(request: Request):
        _, guest = current(request)
        return {"name": guest.name}

    @app.get("/api/models")
    async def models(request: Request):
        cfg, _ = current(request)
        return [{"id": m.id, "label": m.label} for m in cfg.models]

    @app.get("/api/conversations")
    async def conversations(request: Request):
        _, guest = current(request)
        summaries = (await qivis.get("/api/rhizomes")).json()
        mine = [s for s in summaries if f"guest:{guest.id}" in s.get("tags", [])]
        out = []
        for s in mine:
            rhizome = (await qivis.get(f"/api/rhizomes/{s['rhizome_id']}")).json()
            if (rhizome.get("metadata") or {}).get("guest", {}).get("id") != guest.id:
                continue
            first = next(
                (
                    n
                    for n in sorted(rhizome["nodes"], key=lambda n: n["created_at"])
                    if n["role"] == "user"
                ),
                None,
            )
            out.append(
                {
                    "id": s["rhizome_id"],
                    "model": rhizome["metadata"]["guest"].get("model_label"),
                    "preview": (first["content"][:80] if first else ""),
                    "created_at": s["created_at"],
                    "updated_at": s["updated_at"],
                }
            )
        return sorted(out, key=lambda c: c["updated_at"], reverse=True)

    @app.post("/api/conversations", status_code=201)
    async def new_conversation(body: NewConversation, request: Request):
        cfg, guest = current(request)
        model = cfg.model(body.model_id)
        if model is None:
            raise HTTPException(status_code=400, detail="Unknown model")
        existing = [
            s
            for s in (await qivis.get("/api/rhizomes")).json()
            if f"guest:{guest.id}" in s.get("tags", [])
        ]
        if len(existing) >= cfg.limits.max_conversations:
            raise HTTPException(status_code=429, detail="Conversation limit reached")
        metadata = {
            "generation_mode": model.generation_mode,
            "stream_responses": True,
            "guest": {
                "id": guest.id,
                "name": guest.name,
                "model_id": model.id,
                "model_label": model.label,
            },
            "tags": ["guest", f"guest:{guest.id}"],
            "folders": ["Guests"],
        }
        if model.prompt_template:
            metadata["prompt_template"] = model.prompt_template
        created = await qivis.post(
            "/api/rhizomes",
            json={
                "title": f"Guest · {guest.name} · {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}",
                "default_model": model.model,
                "default_provider": model.provider,
                "default_sampling_params": model.sampling_params or None,
                "metadata": metadata,
            },
        )
        created.raise_for_status()
        return {"id": created.json()["rhizome_id"], "model": model.label}

    @app.get("/api/conversations/{rid}")
    async def conversation(rid: str, request: Request, choose: str = ""):
        _, guest = current(request)
        rhizome = await owned(rid, guest)
        label = rhizome["metadata"]["guest"].get("model_label", "Model")
        path = _display_path(rhizome["nodes"], set(filter(None, choose.split(","))))
        return {
            "id": rid,
            "model": label,
            "nodes": [_guest_node(n, sibs, label) for n, sibs in path],
        }

    @app.post("/api/conversations/{rid}/messages")
    async def send(rid: str, body: NewMessage, request: Request):
        cfg, guest = current(request)
        content = body.content.strip()
        if not content:
            raise HTTPException(status_code=400, detail="Empty message")
        if len(content) > cfg.limits.max_message_chars:
            raise HTTPException(
                status_code=413,
                detail=f"Messages are limited to {cfg.limits.max_message_chars} characters",
            )
        rhizome = await owned(rid, guest)
        by_id = {n["node_id"]: n for n in rhizome["nodes"]}
        if body.parent_id is None:
            if rhizome["nodes"]:
                raise HTTPException(status_code=400, detail="Reply to the latest message")
        elif body.parent_id not in by_id or by_id[body.parent_id]["role"] != "assistant":
            raise HTTPException(status_code=400, detail="Reply to the latest message")
        model = model_for(cfg, rhizome)
        check_rate(cfg, guest)
        user = await qivis.post(
            f"/api/rhizomes/{rid}/nodes",
            json={
                "content": content,
                "role": "user",
                "parent_id": body.parent_id,
                "participant_name": guest.name,
            },
        )
        user.raise_for_status()
        user_node = user.json()
        label = rhizome["metadata"]["guest"].get("model_label", model.label)

        async def stream() -> AsyncIterator[str]:
            yield _sse("user", _guest_node(user_node, [user_node], label))
            async for chunk in relay(rid, user_node["node_id"], model, label):
                yield chunk

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/conversations/{rid}/regenerate")
    async def regenerate(rid: str, body: Regenerate, request: Request):
        cfg, guest = current(request)
        rhizome = await owned(rid, guest)
        node = next((n for n in rhizome["nodes"] if n["node_id"] == body.node_id), None)
        # A reply: generate a new sibling of it. The guest's own message left
        # unanswered (e.g. a failed generation): generate its first reply.
        if node is not None and node["role"] == "assistant" and node["parent_id"] is not None:
            parent_id = node["parent_id"]
        elif (
            node is not None
            and node["role"] == "user"
            and not any(n["parent_id"] == node["node_id"] for n in rhizome["nodes"])
        ):
            parent_id = node["node_id"]
        else:
            raise HTTPException(status_code=400, detail="Can only try again on a reply")
        model = model_for(cfg, rhizome)
        check_rate(cfg, guest)
        label = rhizome["metadata"]["guest"].get("model_label", model.label)
        return StreamingResponse(
            relay(rid, parent_id, model, label),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app
