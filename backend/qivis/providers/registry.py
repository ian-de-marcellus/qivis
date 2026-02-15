"""Provider registry: stores configured LLM provider instances."""

from qivis.providers.base import LLMProvider

_providers: dict[str, LLMProvider] = {}


def register_provider(provider: LLMProvider) -> None:
    """Register a provider instance by name."""
    _providers[provider.name] = provider


def get_provider(name: str) -> LLMProvider:
    """Get a registered provider by name. Raises ProviderNotFoundError if not found."""
    try:
        return _providers[name]
    except KeyError:
        available = ", ".join(_providers.keys()) or "(none)"
        raise ProviderNotFoundError(
            f"Provider '{name}' not registered. Available: {available}"
        )


def clear_providers() -> None:
    """Clear all registered providers. Used in tests."""
    _providers.clear()


class ProviderNotFoundError(Exception):
    pass
