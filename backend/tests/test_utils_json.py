"""Tests for consolidated JSON parsing utilities (Interlude)."""

from qivis.utils.json import json_str, parse_json_field, parse_json_or_none


class TestParseJsonField:
    """parse_json_field: strict dict parser for metadata, sampling_params."""

    def test_from_json_string(self):
        assert parse_json_field('{"key": "value"}') == {"key": "value"}

    def test_from_dict(self):
        assert parse_json_field({"key": "value"}) == {"key": "value"}

    def test_none_returns_none(self):
        assert parse_json_field(None) is None

    def test_empty_dict_returns_none(self):
        assert parse_json_field({}) is None

    def test_empty_string_returns_none(self):
        assert parse_json_field("") is None

    def test_invalid_json_returns_none(self):
        assert parse_json_field("not json") is None

    def test_json_list_returns_none(self):
        """Lists are not dicts — parse_json_field only returns dicts."""
        assert parse_json_field("[1, 2, 3]") is None

    def test_nested_dict(self):
        result = parse_json_field('{"a": {"b": 1}}')
        assert result == {"a": {"b": 1}}


class TestParseJsonOrNone:
    """parse_json_or_none: permissive parser for node fields (dicts, lists)."""

    def test_from_json_dict_string(self):
        assert parse_json_or_none('{"key": "value"}') == {"key": "value"}

    def test_from_json_list_string(self):
        assert parse_json_or_none("[1, 2, 3]") == [1, 2, 3]

    def test_dict_passthrough(self):
        d = {"key": "value"}
        assert parse_json_or_none(d) is d

    def test_list_passthrough(self):
        lst = [1, 2, 3]
        assert parse_json_or_none(lst) is lst

    def test_none_returns_none(self):
        assert parse_json_or_none(None) is None

    def test_invalid_json_returns_none(self):
        assert parse_json_or_none("not json") is None

    def test_empty_string_returns_none(self):
        assert parse_json_or_none("") is None


class TestJsonStr:
    """json_str: serialize to JSON string for CSV cells."""

    def test_none_returns_empty(self):
        assert json_str(None) == ""

    def test_dict_serializes(self):
        result = json_str({"key": "value"})
        assert '"key"' in result
        assert '"value"' in result

    def test_list_serializes(self):
        assert json_str([1, 2]) == "[1, 2]"

    def test_json_string_roundtrips(self):
        """A valid JSON string is parsed then re-serialized (normalized)."""
        result = json_str('{"a":  1}')
        assert result == '{"a": 1}'

    def test_non_json_string_passthrough(self):
        """Non-JSON strings pass through unchanged."""
        assert json_str("plain text") == "plain text"
