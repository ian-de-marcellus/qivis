"""Consolidated JSON parsing utilities.

Replaces scattered _parse_json_field(), maybe_json(), _parse_json_or_raw(),
and _json_str() with consistent, well-typed functions.
"""

import json
from typing import Any


def parse_json_field(raw: str | dict | None) -> dict[str, Any] | None:
    """Parse a JSON string or dict, returning None on failure or empty.

    For metadata, sampling_params, and other dict-valued DB fields.
    Returns None for: None, empty string, empty dict, invalid JSON, non-dict JSON.
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw if raw else None
    if isinstance(raw, str):
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed:
                return parsed
        except (ValueError, TypeError):
            pass
    return None


def parse_json_or_none(raw: str | dict | list | None) -> dict | list | None:
    """Parse a JSON string or return structured value as-is, None on failure.

    For node fields (usage, logprobs, context_usage) that may be dict or list.
    Accepts dicts and lists as-is without re-parsing.
    Returns None for: None, empty string, invalid JSON.
    """
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None
    return None


def json_str(value: str | dict | list | None) -> str:
    """Serialize to JSON string for CSV cells. Empty string for None.

    If input is already a JSON string, parses then re-serializes (normalizes).
    Non-JSON strings pass through unchanged.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return json.dumps(parsed)
        except (ValueError, TypeError):
            return value
    return json.dumps(value)
