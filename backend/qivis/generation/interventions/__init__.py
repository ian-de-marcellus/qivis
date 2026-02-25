"""Context intervention pipeline for research-oriented context transforms.

This module provides an extensible architecture for applying configurable
transforms to the generation context before it reaches the LLM provider.

Core abstractions:
- ContextIntervention: ABC for a single composable transform
- InterventionContext: data flowing through the pipeline
- InterventionPipeline: ordered execution of interventions (pre/post eviction)
- InterventionRegistry: type lookup and instantiation from config
- InterventionConfig: Pydantic model for serialized intervention settings
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class InterventionContext:
    """Mutable state passed through the intervention pipeline.

    Fields:
        messages: the message list (parallel to node_ids)
        system_prompt: system prompt text (interventions may null this)
        node_ids: node IDs parallel to messages
        model: the resolved model name
        metadata: rhizome metadata (read-only reference)
        mode: "chat" or "completion"
    """

    messages: list[dict[str, str]]
    system_prompt: str | None
    node_ids: list[str]
    model: str
    metadata: dict[str, Any] = field(default_factory=dict)
    mode: str = "chat"
    created_ats: list[str | None] = field(default_factory=list)


class InterventionConfig(BaseModel):
    """Serialized configuration for a single intervention.

    Stored in rhizome metadata under `context_interventions`.
    """

    type: str
    enabled: bool = True
    config: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class ContextIntervention(ABC):
    """A composable transform on the generation context.

    Subclasses must define:
        type_name: unique identifier for this intervention type
        phase: "pre_eviction" or "post_eviction"
        apply(): the transform logic
    """

    type_name: ClassVar[str]
    phase: ClassVar[str]  # "pre_eviction" or "post_eviction"

    @abstractmethod
    def apply(self, ctx: InterventionContext) -> InterventionContext:
        """Transform the context. Returns the (possibly modified) context."""
        ...

    @classmethod
    def config_schema(cls) -> type | None:
        """Return the Pydantic model for this intervention's config, or None."""
        return None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class InterventionPipeline:
    """Runs interventions in order, split by phase."""

    def __init__(self, interventions: list[ContextIntervention]) -> None:
        self._interventions = interventions

    def run_pre_eviction(self, ctx: InterventionContext) -> InterventionContext:
        """Apply all pre_eviction interventions in order."""
        for intervention in self._interventions:
            if intervention.phase == "pre_eviction":
                ctx = intervention.apply(ctx)
        return ctx

    def run_post_eviction(self, ctx: InterventionContext) -> InterventionContext:
        """Apply all post_eviction interventions in order."""
        for intervention in self._interventions:
            if intervention.phase == "post_eviction":
                ctx = intervention.apply(ctx)
        return ctx

    def get_active_configs(self) -> list[dict[str, Any]]:
        """Return snapshot-friendly list of active intervention configs."""
        return [
            {"type": i.type_name, "phase": i.phase}
            for i in self._interventions
        ]

    @property
    def is_empty(self) -> bool:
        return len(self._interventions) == 0


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class InterventionRegistry:
    """Maps type_name → intervention class. Creates instances from config."""

    def __init__(self) -> None:
        self._types: dict[str, type[ContextIntervention]] = {}

    def register(self, cls: type[ContextIntervention]) -> None:
        """Register an intervention class by its type_name."""
        self._types[cls.type_name] = cls

    def get(self, type_name: str) -> type[ContextIntervention] | None:
        """Look up an intervention class by type_name."""
        return self._types.get(type_name)

    def create(self, config: InterventionConfig) -> ContextIntervention | None:
        """Instantiate an intervention from config. Returns None if disabled or unknown."""
        if not config.enabled:
            return None
        cls = self._types.get(config.type)
        if cls is None:
            return None
        return cls(**config.config)

    def create_pipeline(self, configs: list[InterventionConfig]) -> InterventionPipeline:
        """Create a pipeline from a list of configs, skipping disabled/unknown."""
        interventions = []
        for config in configs:
            intervention = self.create(config)
            if intervention is not None:
                interventions.append(intervention)
        return InterventionPipeline(interventions)

    def available_types(self) -> list[dict[str, Any]]:
        """Return info about all registered intervention types."""
        return [
            {
                "type_name": cls.type_name,
                "phase": cls.phase,
                "description": cls.__doc__ or "",
            }
            for cls in self._types.values()
        ]


# ---------------------------------------------------------------------------
# Global registry (populated by built-in types on import)
# ---------------------------------------------------------------------------

default_registry = InterventionRegistry()


def _register_builtins() -> None:
    """Register all built-in intervention types."""
    from qivis.generation.interventions.system_prompt_reposition import SystemPromptReposition
    from qivis.generation.interventions.reminder_injection import ReminderInjection
    from qivis.generation.interventions.message_wrapper import MessageWrapper

    default_registry.register(SystemPromptReposition)
    default_registry.register(ReminderInjection)
    default_registry.register(MessageWrapper)


_register_builtins()
