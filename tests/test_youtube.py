"""Tests for the YouTube ingestion service."""
import pytest

from app.services.youtube import extract_video_id, _build_raw_text, _detect_language


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
