"""Guest portal configuration: guests, model allowlist, limits.

Lives in a gitignored JSON file (default backend/guest_config.json, or
QIVIS_GUEST_CONFIG). Only hashes of invite tokens are stored. The server
re-reads the file when it changes, so revoking a guest takes effect at once.
"""

import json
import os
import secrets
from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "guest_config.json"


class GuestModel(BaseModel):
    """A model guests may talk to."""

    id: str
    label: str
    provider: str
    model: str
    generation_mode: str = "chat"  # rhizome metadata: "chat" or "completion"
    prompt_template: str | None = None  # e.g. "llama3" for completion mode
    sampling_params: dict = Field(default_factory=dict)


class Guest(BaseModel):
    id: str
    name: str
    token_sha256: str
    created_at: str
    revoked: bool = False


class Limits(BaseModel):
    max_message_chars: int = 4000
    messages_per_minute: int = 12  # messages + regenerations
    max_conversations: int = 100


class GuestConfig(BaseModel):
    session_secret: str
    public_url: str = ""  # e.g. https://host.tailnet.ts.net (for invite links)
    qivis_url: str = "http://127.0.0.1:8000"
    guests: list[Guest] = Field(default_factory=list)
    models: list[GuestModel] = Field(default_factory=list)
    limits: Limits = Field(default_factory=Limits)

    def guest(self, guest_id: str) -> Guest | None:
        return next((g for g in self.guests if g.id == guest_id and not g.revoked), None)

    def model(self, model_id: str) -> GuestModel | None:
        return next((m for m in self.models if m.id == model_id), None)


def config_path() -> Path:
    return Path(os.environ.get("QIVIS_GUEST_CONFIG", DEFAULT_PATH))


def new_config() -> GuestConfig:
    return GuestConfig(session_secret=secrets.token_urlsafe(32))


def load(path: Path) -> GuestConfig:
    return GuestConfig.model_validate(json.loads(path.read_text()))


def save(cfg: GuestConfig, path: Path) -> None:
    path.write_text(cfg.model_dump_json(indent=2) + "\n")
    path.chmod(0o600)


class ConfigStore:
    """Loads the config, reloading when the file changes on disk."""

    def __init__(self, path: Path):
        self.path = path
        self._mtime: float | None = None
        self._cfg: GuestConfig | None = None

    def get(self) -> GuestConfig:
        mtime = self.path.stat().st_mtime
        if self._cfg is None or mtime != self._mtime:
            self._cfg, self._mtime = load(self.path), mtime
        return self._cfg
