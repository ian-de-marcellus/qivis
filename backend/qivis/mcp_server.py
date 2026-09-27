"""MCP server: let other models (e.g. connectome agents) talk to local models.

Run over stdio, launched by the calling agent's host:

    uv run --project /path/to/qivis/backend python -m qivis.mcp_server

Environment:
    QIVIS_URL          Qivis backend (default http://127.0.0.1:8000)
    QIVIS_MCP_CALLER   the calling agent's name, recorded on its turns (default "Agent")
    QIVIS_MCP_MODELS   optional comma-separated allowlist of model labels or ids;
                       default: every profiled model (model_defaults.json)

Every conversation is recorded in Qivis as a rhizome in the "Connectome"
folder, tagged by caller and model, with the caller named on its turns and the
model's settings recorded as usual. The server keeps no state of its own: the
caller's latest conversation with a model is found from those tags.
"""

import asyncio
import os
import re
from datetime import UTC, datetime

import httpx
from mcp.server.mcpserver import MCPServer

FOLDER = "Connectome"
MAX_TEXT = 12_000


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


class QivisBridge:
    """The tools' logic, over Qivis's HTTP API."""

    def __init__(self, client: httpx.AsyncClient, caller: str, allowlist: list[str] | None = None):
        self.q = client
        self.caller = caller
        self.caller_tag = f"caller:{_slug(caller)}"
        self.allowlist = [a.strip() for a in (allowlist or []) if a.strip()]
        self._sending = asyncio.Lock()  # one exchange at a time

    # -- models --

    async def models(self) -> list[dict]:
        entries = (await self.q.get("/api/models")).raise_for_status().json()
        if self.allowlist:
            return [e for e in entries if e["label"] in self.allowlist or e["id"] in self.allowlist
                    or e["model"] in self.allowlist]
        return [e for e in entries if e["source"] == "profile"]

    async def resolve(self, name: str) -> dict:
        models = await self.models()
        for m in models:
            if name in (m["label"], m["id"], m["model"]) or name.lower() == m["label"].lower():
                return m
        names = ", ".join(m["label"] for m in models) or "none configured"
        raise ValueError(f"Unknown model {name!r}. Available: {names}")

    # -- conversations --

    async def _conversations(self, model: dict | None = None) -> list[dict]:
        summaries = (await self.q.get("/api/rhizomes")).raise_for_status().json()
        tags = {"connectome", self.caller_tag} | ({f"model:{model['id']}"} if model else set())
        mine = [s for s in summaries if tags <= set(s.get("tags", []))]
        return sorted(mine, key=lambda s: s["updated_at"], reverse=True)

    async def _create(self, model: dict) -> str:
        rid = (await self.q.post("/api/rhizomes", json={
            "title": f"{self.caller} ↔ {model['label']} · {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}",
            "default_provider": model["provider"],
            "default_model": model["model"],
        })).raise_for_status().json()["rhizome_id"]
        metadata = {
            "generation_mode": model["mode"],
            "prompt_template": "auto",
            "stream_responses": True,
            "connectome": {"caller": self.caller, "model_id": model["id"], "model_label": model["label"]},
            "tags": ["connectome", self.caller_tag, f"model:{model['id']}"],
            "folders": [FOLDER],
        }
        (await self.q.patch(f"/api/rhizomes/{rid}", json={"metadata": metadata})).raise_for_status()
        return rid

    async def _owned(self, rid: str) -> dict:
        r = await self.q.get(f"/api/rhizomes/{rid}")
        if r.status_code != 200:
            raise ValueError(f"No conversation {rid!r}")
        rhizome = r.json()
        if self.caller_tag not in (rhizome.get("metadata") or {}).get("tags", []):
            raise ValueError(f"No conversation {rid!r}")
        return rhizome

    @staticmethod
    def _path(nodes: list[dict]) -> list[dict]:
        """The current line of the conversation: newest child at each step."""
        children: dict[str | None, list[dict]] = {}
        for n in nodes:
            children.setdefault(n["parent_id"], []).append(n)
        path, parent = [], None
        while children.get(parent):
            pick = max(children[parent], key=lambda n: n["created_at"])
            path.append(pick)
            parent = pick["node_id"]
        return path

    async def new_conversation(self, model_name: str) -> str:
        model = await self.resolve(model_name)
        await self._create(model)
        return model["label"]

    async def _conversation_for(self, model: dict, conversation_id: str | None) -> str:
        if conversation_id:
            rhizome = await self._owned(conversation_id)
            if (rhizome["metadata"].get("connectome") or {}).get("model_id") != model["id"]:
                raise ValueError(f"Conversation {conversation_id!r} is with a different model")
            return rhizome["rhizome_id"]
        existing = await self._conversations(model)
        return existing[0]["rhizome_id"] if existing else await self._create(model)

    async def send(self, model_name: str, text: str, conversation_id: str | None = None) -> dict:
        text = text.strip()
        if not text:
            raise ValueError("Nothing to send: text is empty.")
        if len(text) > MAX_TEXT:
            raise ValueError(f"Message is {len(text)} characters; the limit is {MAX_TEXT}.")
        model = await self.resolve(model_name)
        async with self._sending:
            rid = await self._conversation_for(model, conversation_id)
            path = self._path((await self._owned(rid))["nodes"])
            # If the last attempt went unanswered, send beside it: the thread
            # continues cleanly and the failed attempt stays on record as a branch.
            while path and path[-1]["role"] == "user":
                path = path[:-1]
            parent = path[-1]["node_id"] if path else None
            user = (await self.q.post(f"/api/rhizomes/{rid}/nodes", json={
                "content": text, "role": "user", "parent_id": parent,
                "participant_name": self.caller,
            })).raise_for_status().json()
            r = await self.q.post(f"/api/rhizomes/{rid}/nodes/{user['node_id']}/generate",
                                  json={"provider": model["provider"], "model": model["model"]})
            if r.status_code >= 300:
                try:
                    why = r.json().get("detail", r.text)
                except ValueError:
                    why = r.text
                raise RuntimeError(
                    f"Not answered: {model['label']} couldn't reply ({why}). Your message was not "
                    "added to the conversation; you can send it again."
                )
            return {"model": model["label"], "reply": r.json()["content"], "conversation_id": rid}

    async def conversations(self, model_name: str | None = None) -> list[dict]:
        model = await self.resolve(model_name) if model_name else None
        out = []
        for s in (await self._conversations(model))[:20]:
            rh = (await self.q.get(f"/api/rhizomes/{s['rhizome_id']}")).json()
            path = self._path(rh["nodes"])
            first = next((n["content"] for n in path if n["role"] == "user"), "")
            out.append({
                "conversation_id": s["rhizome_id"],
                "model": (rh["metadata"].get("connectome") or {}).get("model_label"),
                "turns": sum(1 for n in path if n["role"] == "user"),
                "started_with": first[:120],
                "updated_at": s["updated_at"],
            })
        return out

    async def read(self, model_name: str, last: int | None = None,
                   conversation_id: str | None = None) -> str:
        model = await self.resolve(model_name)
        if conversation_id:
            rh = await self._owned(conversation_id)
        else:
            existing = await self._conversations(model)
            if not existing:
                return f"No conversation with {model['label']} yet."
            rh = await self._owned(existing[0]["rhizome_id"])
        # Only answered exchanges read as the conversation
        full = self._path(rh["nodes"])
        path = [n for i, n in enumerate(full)
                if n["role"] == "assistant" or (i + 1 < len(full) and full[i + 1]["role"] == "assistant")]
        if not path:
            return f"No messages with {model['label']} in this conversation yet."
        if last and last > 0:
            path = path[-int(last):]
        return "\n\n".join(
            f"{'You' if n['role'] == 'user' else model['label']}: {n.get('edited_content') or n['content']}"
            for n in path
        )


def build_server(bridge: QivisBridge) -> MCPServer:
    server = MCPServer(
        name="qivis",
        instructions=(
            "Talk with locally trained models (for example Sun, an electronic mind trained by Ian). "
            "Use list_models to see who's available, then send_message to talk; conversations "
            "continue across calls. Conversations are recorded in Ian's research tool, Qivis."
        ),
    )

    @server.tool()
    async def models_list() -> str:
        """List the local models you can talk to."""
        models = await bridge.models()
        if not models:
            return "No models are available right now."
        return "\n".join(f"- {m['label']} ({m['mode']} model)" for m in models)

    @server.tool()
    async def model_send(model: str, text: str, conversation_id: str | None = None) -> str:
        """Send a message to a model (by name, from models_list) and wait for its reply.

        Continues your current conversation with that model (use model_new_conversation
        to start fresh, or pass a conversation_id from model_conversations). If the model
        was asleep, the first reply can take a few seconds while it wakes.
        """
        return (await bridge.send(model, text, conversation_id))["reply"]

    @server.tool()
    async def model_read(model: str, last: int | None = None, conversation_id: str | None = None) -> str:
        """Read your current conversation with a model (optionally only the last N messages)."""
        return await bridge.read(model, last, conversation_id)

    @server.tool()
    async def model_new_conversation(model: str) -> str:
        """Start a new conversation with a model. Earlier ones are kept and can be resumed."""
        return f"Started a new conversation with {await bridge.new_conversation(model)}."

    @server.tool()
    async def model_conversations(model: str | None = None) -> str:
        """List your recent conversations (optionally with one model), newest first."""
        convs = await bridge.conversations(model)
        if not convs:
            return "No conversations yet."
        return "\n".join(
            f"- {c['conversation_id']}: with {c['model']}, {c['turns']} messages from you, "
            f"started with {c['started_with']!r} (last active {c['updated_at'][:16]})"
            for c in convs
        )

    return server


def main() -> None:
    client = httpx.AsyncClient(base_url=os.environ.get("QIVIS_URL", "http://127.0.0.1:8000"),
                               timeout=httpx.Timeout(600, connect=10))
    allow = os.environ.get("QIVIS_MCP_MODELS")
    bridge = QivisBridge(client, os.environ.get("QIVIS_MCP_CALLER", "Agent"),
                         allow.split(",") if allow else None)
    build_server(bridge).run("stdio")


if __name__ == "__main__":
    main()
