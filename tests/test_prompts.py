"""Tests for LLM prompt builder language hints."""
import pytest

from app.services.llm.prompts import (
    build_chapter_messages,
    build_chapter_messages_chunk,
    build_glossary_messages,
    build_mind_map_messages,
    build_summary_messages,
)

_TRANSCRIPT = "Sample transcript text."


class TestSummaryPromptLanguageHint:
    def test_english_no_hint(self):
        msgs = build_summary_messages(_TRANSCRIPT, language_code="en")
        system = msgs[0].content
        assert "<language>" not in system

    def test_russian_has_hint(self):
        msgs = build_summary_messages(_TRANSCRIPT, language_code="ru")
        system = msgs[0].content
        assert "<language>" in system
        assert "Russian" in system
        assert "JSON keys must remain in English" in system

    def test_default_is_english(self):
        msgs = build_summary_messages(_TRANSCRIPT)
        system = msgs[0].content
        assert "<language>" not in system


class TestChapterPromptLanguageHint:
    def test_english_no_hint(self):
        msgs = build_chapter_messages(_TRANSCRIPT, language_code="en")
        system = msgs[0].content
        assert "<language>" not in system

    def test_spanish_has_hint(self):
        msgs = build_chapter_messages(_TRANSCRIPT, language_code="es")
        system = msgs[0].content
        assert "Spanish" in system

    def test_chunked_inherits_hint(self):
        msgs = build_chapter_messages_chunk(
            _TRANSCRIPT, 1, 2, "00:00:00", "00:15:00", language_code="de",
        )
        system = msgs[0].content
        assert "German" in system


class TestMindMapPromptLanguageHint:
    def test_english_no_hint(self):
        msgs = build_mind_map_messages(_TRANSCRIPT, language_code="en")
        system = msgs[0].content
        assert "<language>" not in system

    def test_french_has_hint(self):
        msgs = build_mind_map_messages(_TRANSCRIPT, language_code="fr")
        system = msgs[0].content
        assert "French" in system


class TestGlossaryPromptLanguageHint:
    def test_english_no_hint(self):
        msgs = build_glossary_messages(_TRANSCRIPT, language_code="en")
        system = msgs[0].content
        assert "<language>" not in system

    def test_ukrainian_has_hint(self):
        msgs = build_glossary_messages(_TRANSCRIPT, language_code="uk")
        system = msgs[0].content
        assert "Ukrainian" in system
