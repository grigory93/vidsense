"""Tests for app.config Settings validation."""

from app.config import Settings


class TestParseAppAllowedHosts:
    def test_json_array_string(self):
        s = Settings.model_validate(
            {"app_allowed_hosts": '["api.example.com", "other.example.com"]'}
        )
        assert s.app_allowed_hosts == ["api.example.com", "other.example.com"]

    def test_invalid_json_starting_with_bracket_falls_back_without_raising(self):
        """Malformed pseudo-JSON (e.g. missing quotes) must not crash startup."""
        s = Settings.model_validate({"app_allowed_hosts": "[localhost]"})
        assert s.app_allowed_hosts == ["[localhost]"]

    def test_comma_separated_string(self):
        s = Settings.model_validate({"app_allowed_hosts": "vidsense.info, localhost, 127.0.0.1"})
        assert s.app_allowed_hosts == ["vidsense.info", "localhost", "127.0.0.1"]

    def test_empty_string(self):
        s = Settings.model_validate({"app_allowed_hosts": ""})
        assert s.app_allowed_hosts == []

    def test_whitespace_only_string(self):
        s = Settings.model_validate({"app_allowed_hosts": "   "})
        assert s.app_allowed_hosts == []

    def test_list_passthrough(self):
        s = Settings.model_validate({"app_allowed_hosts": ["a.example.com", "b.example.com"]})
        assert s.app_allowed_hosts == ["a.example.com", "b.example.com"]

    def test_json_decode_error_unclosed_bracket_falls_back(self):
        s = Settings.model_validate({"app_allowed_hosts": "[foo, bar"})
        assert s.app_allowed_hosts == ["[foo", "bar"]
