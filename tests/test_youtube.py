"""Tests for the YouTube ingestion service."""
from unittest.mock import MagicMock, patch

import pytest

from youtube_transcript_api import NoTranscriptFound

from app.models.db import TranscriptSourceType
from app.services.youtube import extract_video_id, _build_raw_text, _detect_language, _fetch_transcript


class TestExtractVideoId:
    def test_standard_watch_url(self):
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_youtu_be(self):
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self):
        assert extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_shorts_url(self):
        assert extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_url_with_extra_params(self):
        assert (
            extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PL123")
            == "dQw4w9WgXcQ"
        )

    def test_invalid_url_returns_none(self):
        assert extract_video_id("https://vimeo.com/12345678") is None

    def test_empty_string_returns_none(self):
        assert extract_video_id("") is None

    def test_plain_text_returns_none(self):
        assert extract_video_id("not a url at all") is None


class TestBuildRawText:
    def test_joins_segments(self):
        segments = [{"text": "Hello", "start": 0, "duration": 1}, {"text": "world", "start": 1, "duration": 1}]
        assert _build_raw_text(segments) == "Hello world"

    def test_skips_empty_text(self):
        segments = [{"text": "Hello", "start": 0, "duration": 1}, {"text": "", "start": 1, "duration": 1}]
        assert _build_raw_text(segments) == "Hello"

    def test_empty_segments(self):
        assert _build_raw_text([]) == ""


class TestDetectLanguage:
    def test_detects_from_language_field(self):
        assert _detect_language({"language": "en"}) == "en"

    def test_strips_region_code(self):
        assert _detect_language({"language": "en-US"}) == "en"

    def test_falls_back_to_subtitles(self):
        info = {"subtitles": {"en": [{"url": "..."}]}}
        assert _detect_language(info) == "en"

    def test_returns_none_when_no_lang(self):
        assert _detect_language({}) is None


def _make_transcript(language_code: str, is_generated: bool, texts: list[str] | None = None):
    """Build a mock transcript object matching the youtube-transcript-api interface."""
    texts = texts or ["hello"]
    t = MagicMock()
    t.language_code = language_code
    t.is_generated = is_generated

    snippet = MagicMock()
    snippet.text = texts[0]
    snippet.start = 0.0
    snippet.duration = 1.0
    t.fetch.return_value = [snippet]
    return t


class TestFetchTranscriptEnglishVariants:
    """Regression: English variants not in _EN_CODES must still be selected."""

    @patch("app.services.youtube.YouTubeTranscriptApi")
    def test_en_au_manual_is_selected(self, mock_api_cls):
        """An 'en-AU' manual transcript should be picked up, not NO_TRANSCRIPT."""
        t_en_au = _make_transcript("en-AU", is_generated=False)

        transcript_list = MagicMock()
        transcript_list.find_manually_created_transcript.side_effect = NoTranscriptFound("FAKE_ID", ["en-AU"], None)
        transcript_list.find_generated_transcript.side_effect = NoTranscriptFound("FAKE_ID", ["en-AU"], None)
        transcript_list.__iter__ = lambda self: iter([t_en_au])
        mock_api_cls.return_value.list.return_value = transcript_list

        result = _fetch_transcript("FAKE_ID")
        assert not hasattr(result, "error_code"), f"Expected success, got {result}"
        segments, source_type, lang = result
        assert lang == "en"
        assert source_type == TranscriptSourceType.manual

    @patch("app.services.youtube.YouTubeTranscriptApi")
    def test_en_in_generated_is_selected(self, mock_api_cls):
        """An 'en-IN' auto-generated transcript should be picked up."""
        t_en_in = _make_transcript("en-IN", is_generated=True)

        transcript_list = MagicMock()
        transcript_list.find_manually_created_transcript.side_effect = NoTranscriptFound("FAKE_ID", ["en-IN"], None)
        transcript_list.find_generated_transcript.side_effect = NoTranscriptFound("FAKE_ID", ["en-IN"], None)
        transcript_list.__iter__ = lambda self: iter([t_en_in])
        mock_api_cls.return_value.list.return_value = transcript_list

        result = _fetch_transcript("FAKE_ID")
        assert not hasattr(result, "error_code"), f"Expected success, got {result}"
        segments, source_type, lang = result
        assert lang == "en"
        assert source_type == TranscriptSourceType.auto_generated

    @patch("app.services.youtube.YouTubeTranscriptApi")
    def test_en_au_preferred_over_other_languages(self, mock_api_cls):
        """English variant should be preferred over non-English transcripts."""
        t_en_au = _make_transcript("en-AU", is_generated=False)
        t_es = _make_transcript("es", is_generated=False)

        transcript_list = MagicMock()
        transcript_list.find_manually_created_transcript.side_effect = NoTranscriptFound("FAKE_ID", ["en-AU", "es"], None)
        transcript_list.find_generated_transcript.side_effect = NoTranscriptFound("FAKE_ID", ["en-AU", "es"], None)
        transcript_list.__iter__ = lambda self: iter([t_es, t_en_au])
        mock_api_cls.return_value.list.return_value = transcript_list

        result = _fetch_transcript("FAKE_ID")
        assert not hasattr(result, "error_code"), f"Expected success, got {result}"
        _, _, lang = result
        assert lang == "en"
