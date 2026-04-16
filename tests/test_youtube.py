"""Tests for the YouTube ingestion service."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from youtube_transcript_api import NoTranscriptFound

from app.models.db import TranscriptSourceType
from app.models.schemas import IngestionError
from app.services.youtube import (
    _build_raw_text,
    _detect_language,
    _fetch_metadata,
    _fetch_top_comments,
    _fetch_transcript,
    _parse_iso8601_duration,
    extract_video_id,
)

# ---------------------------------------------------------------------------
# URL parsing (unchanged)
# ---------------------------------------------------------------------------


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
        segments = [
            {"text": "Hello", "start": 0, "duration": 1},
            {"text": "world", "start": 1, "duration": 1},
        ]
        assert _build_raw_text(segments) == "Hello world"

    def test_skips_empty_text(self):
        segments = [
            {"text": "Hello", "start": 0, "duration": 1},
            {"text": "", "start": 1, "duration": 1},
        ]
        assert _build_raw_text(segments) == "Hello"

    def test_empty_segments(self):
        assert _build_raw_text([]) == ""


# ---------------------------------------------------------------------------
# ISO 8601 duration parser
# ---------------------------------------------------------------------------


class TestParseIso8601Duration:
    def test_hours_minutes_seconds(self):
        assert _parse_iso8601_duration("PT1H2M3S") == 3723

    def test_minutes_only(self):
        assert _parse_iso8601_duration("PT5M") == 300

    def test_seconds_only(self):
        assert _parse_iso8601_duration("PT30S") == 30

    def test_hours_only(self):
        assert _parse_iso8601_duration("PT2H") == 7200

    def test_zero_duration(self):
        assert _parse_iso8601_duration("PT0S") == 0

    def test_days_and_time(self):
        assert _parse_iso8601_duration("P1DT2H3M4S") == 93784

    def test_p0d(self):
        assert _parse_iso8601_duration("P0D") == 0

    def test_empty_string(self):
        assert _parse_iso8601_duration("") is None

    def test_malformed(self):
        assert _parse_iso8601_duration("not-a-duration") is None

    def test_none_input(self):
        assert _parse_iso8601_duration(None) is None


# ---------------------------------------------------------------------------
# Language detection (updated for API v3 field names)
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    def test_detects_from_language_field(self):
        assert _detect_language({"language": "en"}) == "en"

    def test_strips_region_code(self):
        assert _detect_language({"language": "en-US"}) == "en"

    def test_returns_none_when_no_lang(self):
        assert _detect_language({}) is None

    def test_returns_none_for_empty_string(self):
        assert _detect_language({"language": ""}) is None


# ---------------------------------------------------------------------------
# _fetch_metadata via YouTube Data API v3
# ---------------------------------------------------------------------------


def _make_api_response(items=None, status_code=200):
    """Build a mock httpx.Response for the videos.list endpoint."""
    if items is None:
        items = [
            {
                "snippet": {
                    "title": "Test Video",
                    "description": "A test description",
                    "channelTitle": "TestChannel",
                    "channelId": "UC123",
                    "publishedAt": "2024-06-15T10:30:00Z",
                    "thumbnails": {"high": {"url": "https://i.ytimg.com/vi/abc/hq.jpg"}},
                    "tags": ["python", "tutorial"],
                    "categoryId": "27",
                    "defaultAudioLanguage": "en",
                },
                "contentDetails": {"duration": "PT12M34S"},
                "statistics": {"viewCount": "123456", "likeCount": "789"},
            }
        ]
    body = {"items": items}
    resp = httpx.Response(
        status_code=status_code, json=body, request=httpx.Request("GET", "https://test")
    )
    return resp


class TestFetchMetadata:
    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        mock_resp = _make_api_response()
        with patch("app.services.youtube.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _fetch_metadata("test123")

        assert not isinstance(result, IngestionError)
        assert result["title"] == "Test Video"
        assert result["channel"] == "TestChannel"
        assert result["duration"] == 754  # 12*60 + 34
        assert result["view_count"] == 123456
        assert result["like_count"] == 789
        assert result["tags"] == ["python", "tutorial"]
        assert result["category"] == "Education"
        assert result["language"] == "en"
        assert result["upload_date"] == "2024-06-15T10:30:00Z"
        assert "channel/UC123" in result["channel_url"]

    @pytest.mark.asyncio
    async def test_empty_items_returns_error(self):
        mock_resp = _make_api_response(items=[])
        with patch("app.services.youtube.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _fetch_metadata("nonexistent")

        assert isinstance(result, IngestionError)
        assert result.error_code == "METADATA_FETCH_FAILED"

    @pytest.mark.asyncio
    async def test_http_error_returns_ingestion_error(self):
        # 403 = YouTube quota/rate-limit — must be recoverable so the UI
        # shows a "try again later" affordance instead of a dead end.
        error_resp = httpx.Response(
            status_code=403,
            json={"error": {"message": "quotaExceeded"}},
            request=httpx.Request("GET", "https://test"),
        )
        with patch("app.services.youtube.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=error_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _fetch_metadata("forbidden_id")

        assert isinstance(result, IngestionError)
        assert "403" in result.message
        assert result.recoverable is True

    @pytest.mark.asyncio
    async def test_429_returns_recoverable_error(self):
        error_resp = httpx.Response(
            status_code=429,
            json={"error": {"message": "Too Many Requests"}},
            request=httpx.Request("GET", "https://test"),
        )
        with patch("app.services.youtube.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=error_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _fetch_metadata("any_id")

        assert isinstance(result, IngestionError)
        assert result.recoverable is True

    @pytest.mark.asyncio
    async def test_404_is_not_recoverable(self):
        error_resp = httpx.Response(
            status_code=404,
            json={"error": {"message": "Not Found"}},
            request=httpx.Request("GET", "https://test"),
        )
        with patch("app.services.youtube.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=error_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _fetch_metadata("missing_id")

        assert isinstance(result, IngestionError)
        assert result.recoverable is False

    @pytest.mark.asyncio
    async def test_network_error_returns_recoverable_error(self):
        with patch("app.services.youtube.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Network down"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _fetch_metadata("any_id")

        assert isinstance(result, IngestionError)
        assert result.recoverable is True


# ---------------------------------------------------------------------------
# _fetch_top_comments
# ---------------------------------------------------------------------------


class TestFetchTopComments:
    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        body = {
            "items": [
                {
                    "snippet": {
                        "topLevelComment": {
                            "snippet": {
                                "authorDisplayName": "Alice",
                                "textDisplay": "Great video!",
                            }
                        }
                    }
                },
                {
                    "snippet": {
                        "topLevelComment": {
                            "snippet": {
                                "authorDisplayName": "Bob",
                                "textDisplay": "Very informative.",
                            }
                        }
                    }
                },
            ]
        }
        mock_resp = httpx.Response(200, json=body, request=httpx.Request("GET", "https://test"))
        with patch("app.services.youtube.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _fetch_top_comments("test123")

        assert result is not None
        assert len(result) == 2
        assert result[0]["author"] == "Alice"
        assert result[0]["text"] == "Great video!"

    @pytest.mark.asyncio
    async def test_comments_disabled_returns_none(self):
        error_resp = httpx.Response(
            status_code=403,
            json={"error": {"errors": [{"reason": "commentsDisabled"}]}},
            request=httpx.Request("GET", "https://test"),
        )
        with patch("app.services.youtube.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=error_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _fetch_top_comments("no_comments")

        assert result is None

    @pytest.mark.asyncio
    async def test_truncates_long_comments(self):
        long_text = "x" * 500
        body = {
            "items": [
                {
                    "snippet": {
                        "topLevelComment": {
                            "snippet": {
                                "authorDisplayName": "Verbose",
                                "textDisplay": long_text,
                            }
                        }
                    }
                }
            ]
        }
        mock_resp = httpx.Response(200, json=body, request=httpx.Request("GET", "https://test"))
        with patch("app.services.youtube.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _fetch_top_comments("test123")

        assert result is not None
        assert len(result[0]["text"]) == 300


# ---------------------------------------------------------------------------
# Transcript (unchanged — youtube-transcript-api stays)
# ---------------------------------------------------------------------------


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
        transcript_list.find_manually_created_transcript.side_effect = NoTranscriptFound(
            "FAKE_ID", ["en-AU"], None
        )
        transcript_list.find_generated_transcript.side_effect = NoTranscriptFound(
            "FAKE_ID", ["en-AU"], None
        )
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
        transcript_list.find_manually_created_transcript.side_effect = NoTranscriptFound(
            "FAKE_ID", ["en-IN"], None
        )
        transcript_list.find_generated_transcript.side_effect = NoTranscriptFound(
            "FAKE_ID", ["en-IN"], None
        )
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
        transcript_list.find_manually_created_transcript.side_effect = NoTranscriptFound(
            "FAKE_ID", ["en-AU", "es"], None
        )
        transcript_list.find_generated_transcript.side_effect = NoTranscriptFound(
            "FAKE_ID", ["en-AU", "es"], None
        )
        transcript_list.__iter__ = lambda self: iter([t_es, t_en_au])
        mock_api_cls.return_value.list.return_value = transcript_list

        result = _fetch_transcript("FAKE_ID")
        assert not hasattr(result, "error_code"), f"Expected success, got {result}"
        _, _, lang = result
        assert lang == "en"
