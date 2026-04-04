"""Tests for app.lang — language normalization and display names."""
import pytest

from app.lang import language_display_name, normalize_language_code


class TestNormalizeLanguageCode:
    def test_plain_code(self):
        assert normalize_language_code("en") == "en"

    def test_strips_region(self):
        assert normalize_language_code("pt-BR") == "pt"

    def test_strips_underscore_region(self):
        assert normalize_language_code("zh_TW") == "zh"

    def test_lowercases(self):
        assert normalize_language_code("EN") == "en"

    def test_none_defaults_to_en(self):
        assert normalize_language_code(None) == "en"

    def test_empty_string_defaults_to_en(self):
        assert normalize_language_code("") == "en"

    def test_whitespace_defaults_to_en(self):
        assert normalize_language_code("   ") == "en"


class TestLanguageDisplayName:
    def test_known_language(self):
        assert language_display_name("ru") == "Russian"

    def test_with_region(self):
        assert language_display_name("pt-BR") == "Portuguese"

    def test_unknown_code_returns_code(self):
        assert language_display_name("xx") == "xx"

    def test_english(self):
        assert language_display_name("en") == "English"
