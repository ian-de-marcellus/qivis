"""Auto-detect import format from parsed JSON data."""

from typing import Any


class ImportFormatError(Exception):
    """Raised when the import format cannot be detected or is unsupported."""


def detect_format(data: Any) -> str:
    """Detect import format from parsed JSON structure.

    Returns "chatgpt", "claude", or "linear".
    Raises ImportFormatError for unrecognized structures.
    """
    if isinstance(data, dict):
        if "mapping" in data:
            return "chatgpt"
        if "chat_messages" in data:
            return "claude"
        raise ImportFormatError("Unrecognized object format")

    if isinstance(data, list) and len(data) > 0:
        first = data[0]
        if isinstance(first, dict):
            # Array of ChatGPT conversations
            if "mapping" in first:
                return "chatgpt"
            # Array of Claude.ai conversations
            if "chat_messages" in first:
                return "claude"
            # ShareGPT: {from, value}
            if "from" in first or "value" in first:
                return "linear"
            # Generic: {role, content}
            if "role" in first or "content" in first:
                return "linear"

    if isinstance(data, list) and len(data) == 0:
        raise ImportFormatError("Empty array — nothing to import")

    raise ImportFormatError("Unrecognized format")
