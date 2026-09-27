"""Model catalog: named models and the defaults each one carries.

Profiles live in backend/model_defaults.json (gitignored; see
model_defaults.example.json), keyed by model name (for llama.cpp, the name
llama-server reports for the loaded model). A profile can set:

- label             display name in the model picker (e.g. "Sun 1.0.1")
- provider          which provider serves it
- generation_mode   "chat" or "completion"
- prompt_template   completion template, e.g. "llama3" (used when a rhizome
                    leaves its template on "auto")
- logit_bias, bos_tokens   applied by the llama.cpp provider

A model's format belongs to the model, so rhizomes default to "auto" and
each generation uses the profile of the model actually generating.
"""

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "model_defaults.json"


class ModelCatalog:
    def __init__(self, profiles: dict[str, Any] | None = None):
        # Skip notes like "_comment"; only dict entries are model profiles
        self.profiles: dict[str, dict] = {
            name: cfg for name, cfg in (profiles or {}).items()
            if isinstance(cfg, dict) and not name.startswith("_")
        }

    @classmethod
    def load(cls, path: Path | None = None) -> ModelCatalog:
        path = path or Path(os.environ.get("QIVIS_MODEL_DEFAULTS", DEFAULT_PATH))
        return cls(json.loads(path.read_text()) if path.exists() else {})

    def profile(self, model: str | None) -> dict | None:
        return self.profiles.get(model) if model else None

    def entries(self, providers: list) -> list[dict]:
        """Picker entries: profiled models first, then each provider's discovered models."""
        by_name = {p.name: p for p in providers}
        entries: list[dict] = []
        profiled: set[tuple[str, str]] = set()
        for model, cfg in self.profiles.items():
            provider = cfg.get("provider")
            if provider not in by_name:
                continue  # its provider isn't configured on this machine
            profiled.add((provider, model))
            entries.append(self._entry(by_name[provider], model, cfg, "profile"))
        for p in providers:
            for model in p.suggested_models:
                if (p.name, model) not in profiled:
                    entries.append(self._entry(p, model, {}, "discovered"))
        return entries

    @staticmethod
    def _entry(provider, model: str, cfg: dict, source: str) -> dict:
        completion_only = "chat" not in provider.supported_modes
        mode = "completion" if completion_only else cfg.get("generation_mode", "chat")
        return {
            "id": f"{provider.name}:{model}",
            "label": cfg.get("label", model),
            "provider": provider.name,
            "model": model,
            "mode": mode,
            "prompt_template": cfg.get("prompt_template"),
            "source": source,
        }


_catalog = ModelCatalog()


def get_catalog() -> ModelCatalog:
    return _catalog


def set_catalog(catalog: ModelCatalog) -> None:
    global _catalog
    _catalog = catalog
