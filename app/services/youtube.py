"""
YouTube ingestion service.

Responsibilities:
- Parse and validate YouTube URLs
- Fetch video metadata via yt-dlp
- Retrieve available transcripts via youtube-transcript-api
- Cache Video + TranscriptSource in DB to avoid re-ingestion
- Return typed results for all failure states
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import yt_dlp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)
from youtube_transcript_api._errors import VideoUnavailable

from app.config import settings
from app.models.db import (
    AnalysisRun,
    AnalysisRunStatus,
    TranscriptSource,
    TranscriptSourceType,
    Video,
)
from app.models.schemas import IngestionError

# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

_YT_PATTERNS = [
    r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})",
]


def _normalize_url(url: str) -> str:
    """Prepend https:// if URL has no scheme, so scheme-less inputs are accepted."""
    u = (url or "").strip()
    if not u:
        return u
    if re.match(r"^https?://", u, re.IGNORECASE):
        return u
    return "https://" + u


def extract_video_id(url: str) -> str | None:
    """Return the 11-character YouTube video ID from a URL, or None if not found."""
    url = _normalize_url(url)
    for pattern in _YT_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class IngestionResult:
    success: bool
    video: Video | None = None
    transcript_source: TranscriptSource | None = None
    error: IngestionError | None = None
    quality_warning: str | None = None  # non-fatal warning to surface in UI


# ---------------------------------------------------------------------------
# Metadata fetch
# ---------------------------------------------------------------------------

_YDL_OPTS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": False,
}


def _fetch_metadata(video_id: str) -> dict[str, Any] | IngestionError:
    """Use yt-dlp to fetch video metadata synchronously (run in thread)."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(_YDL_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
            return info  # type: ignore[return-value]
    except Exception as exc:
        return IngestionError(
            error_code="METADATA_FETCH_FAILED",
            message=f"Could not retrieve video information: {exc}",
            recoverable=True,
        )


def _detect_language(info: dict[str, Any]) -> str | None:
    """Best-effort language detection from yt-dlp metadata."""
    lang = info.get("language")
    if isinstance(lang, str):
        return lang.split("-")[0].lower()
    # Fall back to subtitles keys
    for key in ("subtitles", "automatic_captions"):
        captions = info.get(key, {})
        if isinstance(captions, dict) and captions:
            first_lang = next(iter(captions))
            return first_lang.split("-")[0].lower()
    return None


# ---------------------------------------------------------------------------
# Transcript retrieval
# ---------------------------------------------------------------------------


def _fetch_transcript(video_id: str) -> tuple[list[dict], TranscriptSourceType, str] | IngestionError:
    """
    Returns (segments, source_type, language_code) on success,
    or an IngestionError on failure.

    Preference order: manual English → auto-generated English.
    """
    try:
        transcript_list = YouTubeTranscriptApi().list(video_id)
    except TranscriptsDisabled:
        return IngestionError(
            error_code="TRANSCRIPTS_DISABLED",
            message="Transcripts are disabled for this video.",
        )
    except VideoUnavailable:
        return IngestionError(
            error_code="VIDEO_UNAVAILABLE",
            message="This video is unavailable or private.",
        )
    except Exception as exc:
        return IngestionError(
            error_code="TRANSCRIPT_FETCH_FAILED",
            message=f"Could not fetch transcript: {exc}",
            recoverable=True,
        )

    # Try manual English first
    try:
        transcript = transcript_list.find_manually_created_transcript(["en", "en-US", "en-GB"])
        segments = transcript.fetch()
        return (
            [{"text": s.text, "start": s.start, "duration": s.duration} for s in segments],
            TranscriptSourceType.manual,
            "en",
        )
    except NoTranscriptFound:
        pass

    # Fall back to auto-generated English
    try:
        transcript = transcript_list.find_generated_transcript(["en", "en-US", "en-GB"])
        segments = transcript.fetch()
        return (
            [{"text": s.text, "start": s.start, "duration": s.duration} for s in segments],
            TranscriptSourceType.auto_generated,
            "en",
        )
    except NoTranscriptFound:
        pass

    # No English transcript at all — check if any transcript exists (non-English)
    try:
        available = list(transcript_list)
        if available:
            langs = [t.language_code for t in available]
            return IngestionError(
                error_code="UNSUPPORTED_LANGUAGE",
                message=(
                    f"No English transcript is available for this video. "
                    f"Available languages: {', '.join(langs)}."
                ),
            )
    except Exception:
        pass

    return IngestionError(
        error_code="NO_TRANSCRIPT",
        message="No transcript or caption source is available for this video.",
    )


def _build_raw_text(segments: list[dict]) -> str:
    """Concatenate transcript segments into a single plain-text string."""
    return " ".join(s["text"].strip() for s in segments if s.get("text"))


# ---------------------------------------------------------------------------
# Main ingestion entry point
# ---------------------------------------------------------------------------


async def ingest_video(
    url: str,
    session: AsyncSession,
) -> IngestionResult:
    """
    Full ingestion pipeline:
    1. Parse URL
    2. Check cache (return existing Video + TranscriptSource if found)
    3. Fetch metadata
    4. Validate duration + language
    5. Fetch transcript
    6. Persist Video + TranscriptSource
    """
    # 1. Parse URL
    video_id = extract_video_id(url)
    if not video_id:
        return IngestionResult(
            success=False,
            error=IngestionError(
                error_code="INVALID_URL",
                message="The URL doesn't look like a valid YouTube video link.",
            ),
        )

    # 2. Check cache — return existing data to avoid re-ingestion
    existing_video = await _get_cached_video(video_id, session)
    if existing_video:
        transcript_source = await _get_cached_transcript(existing_video.id, session)
        if transcript_source:
            quality_warning = _quality_warning(transcript_source)
            return IngestionResult(
                success=True,
                video=existing_video,
                transcript_source=transcript_source,
                quality_warning=quality_warning,
            )

    # 3. Fetch metadata (blocking I/O — run in thread executor in production;
    #    acceptable synchronous call here since yt-dlp has no async API)
    metadata = _fetch_metadata(video_id)
    if isinstance(metadata, IngestionError):
        return IngestionResult(success=False, error=metadata)

    # 4a. Validate duration
    duration_sec: int | None = metadata.get("duration")
    if duration_sec and duration_sec > settings.max_video_duration_sec:
        minutes = duration_sec // 60
        return IngestionResult(
            success=False,
            error=IngestionError(
                error_code="VIDEO_TOO_LONG",
                message=(
                    f"This video is {minutes} minutes long. "
                    f"VidSense currently supports videos up to 90 minutes."
                ),
            ),
        )

    # 4b. Validate language via metadata
    detected_lang = _detect_language(metadata)
    if detected_lang and detected_lang not in settings.supported_languages:
        return IngestionResult(
            success=False,
            error=IngestionError(
                error_code="UNSUPPORTED_LANGUAGE",
                message=(
                    f"VidSense currently supports English-language videos only. "
                    f"Detected language: {detected_lang}."
                ),
            ),
        )

    # 5. Fetch transcript
    transcript_result = _fetch_transcript(video_id)
    if isinstance(transcript_result, IngestionError):
        # If we got a UNSUPPORTED_LANGUAGE error from transcript API, honour it
        return IngestionResult(success=False, error=transcript_result)

    segments, source_type, lang_code = transcript_result
    raw_text = _build_raw_text(segments)

    # 6. Persist
    video = existing_video or Video(
        youtube_id=video_id,
        url=url,
        title=metadata.get("title"),
        duration_sec=duration_sec,
        language=lang_code or detected_lang,
        thumbnail_url=metadata.get("thumbnail"),
        channel_name=metadata.get("uploader") or metadata.get("channel"),
        channel_url=metadata.get("channel_url") or metadata.get("uploader_url"),
        description=metadata.get("description"),
        upload_date=metadata.get("upload_date"),
        view_count=metadata.get("view_count"),
        like_count=metadata.get("like_count"),
    )
    if not existing_video:
        session.add(video)
        await session.flush()  # get video.id

    quality_signal = "auto_generated" if source_type == TranscriptSourceType.auto_generated else "good"
    transcript_source = TranscriptSource(
        video_id=video.id,
        raw_text=raw_text,
        segments_json=json.dumps(segments),
        source_type=source_type,
        quality_signal=quality_signal,
        language_code=lang_code,
    )
    session.add(transcript_source)
    await session.commit()
    await session.refresh(video)
    await session.refresh(transcript_source)

    quality_warning = _quality_warning(transcript_source)
    return IngestionResult(
        success=True,
        video=video,
        transcript_source=transcript_source,
        quality_warning=quality_warning,
    )


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


async def _get_cached_video(youtube_id: str, session: AsyncSession) -> Video | None:
    result = await session.execute(select(Video).where(Video.youtube_id == youtube_id))
    return result.scalar_one_or_none()


async def _get_cached_transcript(video_id: int, session: AsyncSession) -> TranscriptSource | None:
    result = await session.execute(
        select(TranscriptSource)
        .where(TranscriptSource.video_id == video_id)
        .order_by(TranscriptSource.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_transcript_for_video(video_id: int, session: AsyncSession) -> TranscriptSource | None:
    """Public helper: retrieve the cached transcript for an already-ingested video."""
    return await _get_cached_transcript(video_id, session)


async def get_latest_run(video_id: int, session: AsyncSession) -> AnalysisRun | None:
    """Return the most recent AnalysisRun for a video."""
    result = await session.execute(
        select(AnalysisRun)
        .where(AnalysisRun.video_id == video_id)
        .order_by(AnalysisRun.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _quality_warning(ts: TranscriptSource) -> str | None:
    if ts.source_type == TranscriptSourceType.auto_generated:
        return (
            "The transcript for this video was auto-generated. "
            "Summary and chapter quality may be reduced."
        )
    return None
