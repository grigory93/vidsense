"""
YouTube ingestion service.

Responsibilities:
- Parse and validate YouTube URLs
- Fetch video metadata via YouTube Data API v3
- Retrieve available transcripts via youtube-transcript-api
- Cache Video + TranscriptSource in DB to avoid re-ingestion
- Return typed results for all failure states
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)
from youtube_transcript_api._errors import VideoUnavailable

from app.config import settings
from app.lang import normalize_language_code
from app.models.db import (
    AnalysisRun,
    TranscriptSource,
    TranscriptSourceType,
    Video,
)
from app.models.schemas import IngestionError

logger = logging.getLogger(__name__)

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
    quality_warning: str | None = None


# ---------------------------------------------------------------------------
# YouTube Data API v3 helpers
# ---------------------------------------------------------------------------

_YT_API_BASE = "https://www.googleapis.com/youtube/v3"

# YouTube video category IDs -> display names (YouTube's fixed set)
_CATEGORY_MAP: dict[str, str] = {
    "1": "Film & Animation",
    "2": "Autos & Vehicles",
    "10": "Music",
    "15": "Pets & Animals",
    "17": "Sports",
    "18": "Short Movies",
    "19": "Travel & Events",
    "20": "Gaming",
    "21": "Videoblogging",
    "22": "People & Blogs",
    "23": "Comedy",
    "24": "Entertainment",
    "25": "News & Politics",
    "26": "Howto & Style",
    "27": "Education",
    "28": "Science & Technology",
    "29": "Nonprofits & Activism",
    "30": "Movies",
    "31": "Anime/Animation",
    "32": "Action/Adventure",
    "33": "Classics",
    "34": "Comedy",
    "35": "Documentary",
    "36": "Drama",
    "37": "Family",
    "38": "Foreign",
    "39": "Horror",
    "40": "Sci-Fi/Fantasy",
    "41": "Thriller",
    "42": "Shorts",
    "43": "Shows",
    "44": "Trailers",
}

_ISO_DURATION_RE = re.compile(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def _parse_iso8601_duration(iso_str: str) -> int | None:
    """Parse an ISO 8601 duration like ``PT1H2M3S`` into total seconds."""
    if not iso_str:
        return None
    m = _ISO_DURATION_RE.match(iso_str)
    if not m:
        return None
    days = int(m.group(1) or 0)
    hours = int(m.group(2) or 0)
    minutes = int(m.group(3) or 0)
    seconds = int(m.group(4) or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


async def _fetch_metadata(video_id: str) -> dict[str, Any] | IngestionError:
    """Fetch video metadata from YouTube Data API v3."""
    # Pass key via params (not URL string) so it never appears in exception
    # reprs, access logs, or str(request.url) in future middleware.
    params = {
        "id": video_id,
        "part": "snippet,contentDetails,statistics",
        "key": settings.youtube_api_key,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{_YT_API_BASE}/videos", params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        # Treat YouTube API's transient statuses (quotaExceeded / rateLimitExceeded
        # are returned as 403; 429 is short-term throttling; 5xx are server errors)
        # as recoverable so the UI offers "try again later" rather than a dead end.
        recoverable = status == 403 or status == 429 or status >= 500
        return IngestionError(
            error_code="METADATA_FETCH_FAILED",
            message=f"YouTube API returned {status}: {exc.response.text[:200]}",
            recoverable=recoverable,
        )
    except Exception as exc:
        return IngestionError(
            error_code="METADATA_FETCH_FAILED",
            message=f"Could not retrieve video information: {exc}",
            recoverable=True,
        )

    items = data.get("items", [])
    if not items:
        return IngestionError(
            error_code="METADATA_FETCH_FAILED",
            message="Video not found or is unavailable.",
            recoverable=False,
        )

    item = items[0]
    snippet = item.get("snippet", {})
    content_details = item.get("contentDetails", {})
    statistics = item.get("statistics", {})

    thumbnails = snippet.get("thumbnails", {})
    thumbnail_url = (
        thumbnails.get("high", {}).get("url")
        or thumbnails.get("medium", {}).get("url")
        or thumbnails.get("default", {}).get("url")
    )

    category_id = snippet.get("categoryId", "")
    category = _CATEGORY_MAP.get(category_id)

    duration_sec = _parse_iso8601_duration(content_details.get("duration", ""))

    view_count_raw = statistics.get("viewCount")
    like_count_raw = statistics.get("likeCount")

    return {
        "title": snippet.get("title"),
        "description": snippet.get("description"),
        "thumbnail": thumbnail_url,
        "channel": snippet.get("channelTitle"),
        "channel_url": f"https://www.youtube.com/channel/{snippet['channelId']}"
        if snippet.get("channelId")
        else None,
        "upload_date": snippet.get("publishedAt"),
        "duration": duration_sec,
        "view_count": int(view_count_raw) if view_count_raw else None,
        "like_count": int(like_count_raw) if like_count_raw else None,
        "tags": snippet.get("tags", []),
        "category": category,
        "language": snippet.get("defaultAudioLanguage") or snippet.get("defaultLanguage"),
    }


def _detect_language(info: dict[str, Any]) -> str | None:
    """Best-effort language detection from API metadata."""
    lang = info.get("language")
    if isinstance(lang, str) and lang.strip():
        return normalize_language_code(lang)
    return None


async def _fetch_top_comments(video_id: str) -> list[dict[str, str]] | None:
    """Fetch top comments via YouTube Data API v3 (best-effort, returns None on failure)."""
    params = {
        "videoId": video_id,
        "part": "snippet",
        "order": "relevance",
        "maxResults": settings.youtube_max_comments,
        "key": settings.youtube_api_key,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{_YT_API_BASE}/commentThreads", params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.debug("Comments fetch failed for video %s (best-effort, skipping)", video_id)
        return None

    comments: list[dict[str, str]] = []
    max_chars = settings.youtube_max_comment_chars
    for item in data.get("items", []):
        try:
            top = item["snippet"]["topLevelComment"]["snippet"]
            text = (top.get("textDisplay") or "").strip()
            if text:
                comments.append(
                    {
                        "author": top.get("authorDisplayName", ""),
                        "text": text[:max_chars],
                    }
                )
        except (KeyError, TypeError):
            continue
    return comments or None


# ---------------------------------------------------------------------------
# Transcript retrieval
# ---------------------------------------------------------------------------


def _fetch_transcript(
    video_id: str,
) -> tuple[list[dict], TranscriptSourceType, str] | IngestionError:
    """
    Returns (segments, source_type, language_code) on success,
    or an IngestionError on failure.

    Deterministic 4-tier ranking:
      1. Manual English transcript
      2. Auto-generated English transcript
      3. Manual transcript in a supported language (settings.supported_languages order)
      4. Auto-generated transcript in a supported language (same order)
    Falls through to the first available language if none of the above match.
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

    def _to_segments(transcript) -> list[dict]:
        return [
            {"text": s.text, "start": s.start, "duration": s.duration} for s in transcript.fetch()
        ]

    _EN_CODES = ["en", "en-US", "en-GB"]

    # Tier 1: manual English
    try:
        transcript = transcript_list.find_manually_created_transcript(_EN_CODES)
        segments = _to_segments(transcript)
        logger.info("Selected transcript: lang=en, source=manual, video=%s", video_id)
        return (segments, TranscriptSourceType.manual, "en")
    except NoTranscriptFound:
        pass

    # Tier 2: auto-generated English
    try:
        transcript = transcript_list.find_generated_transcript(_EN_CODES)
        segments = _to_segments(transcript)
        logger.info("Selected transcript: lang=en, source=auto_generated, video=%s", video_id)
        return (segments, TranscriptSourceType.auto_generated, "en")
    except NoTranscriptFound:
        pass

    # Build lookup tables for tiers 3-4
    try:
        available = list(transcript_list)
    except Exception:
        available = []

    if not available:
        return IngestionError(
            error_code="NO_TRANSCRIPT",
            message="No transcript or caption source is available for this video.",
        )

    manual_by_lang: dict[str, object] = {}
    generated_by_lang: dict[str, object] = {}
    for t in available:
        lang = normalize_language_code(t.language_code)
        if t.is_generated:
            generated_by_lang.setdefault(lang, t)
        else:
            manual_by_lang.setdefault(lang, t)

    pref_langs = [normalize_language_code(lc) for lc in settings.supported_languages]

    # Tier 3: manual transcript in preferred language order
    for lang in pref_langs:
        if lang in manual_by_lang:
            segments = _to_segments(manual_by_lang[lang])
            logger.info("Selected transcript: lang=%s, source=manual, video=%s", lang, video_id)
            return (segments, TranscriptSourceType.manual, lang)

    # Tier 4: auto-generated transcript in preferred language order
    for lang in pref_langs:
        if lang in generated_by_lang:
            segments = _to_segments(generated_by_lang[lang])
            logger.info(
                "Selected transcript: lang=%s, source=auto_generated, video=%s", lang, video_id
            )
            return (segments, TranscriptSourceType.auto_generated, lang)

    # Fallback: first available manual, then generated
    if manual_by_lang:
        lang, t = next(iter(manual_by_lang.items()))
        segments = _to_segments(t)
        logger.info(
            "Selected transcript: lang=%s, source=manual (fallback), video=%s", lang, video_id
        )
        return (segments, TranscriptSourceType.manual, lang)
    if generated_by_lang:
        lang, t = next(iter(generated_by_lang.items()))
        segments = _to_segments(t)
        logger.info(
            "Selected transcript: lang=%s, source=auto_generated (fallback), video=%s",
            lang,
            video_id,
        )
        return (segments, TranscriptSourceType.auto_generated, lang)

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
    3. Fetch metadata via YouTube Data API v3
    4. Validate duration + language
    5. Fetch transcript
    6. Fetch top comments (best-effort)
    7. Persist Video + TranscriptSource
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

    # 3. Fetch metadata via YouTube Data API v3
    metadata = await _fetch_metadata(video_id)
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

    # 4b. Detect language from metadata (used as fallback for the video record).
    detected_lang = _detect_language(metadata)

    # 5. Fetch transcript (accepts any language; see _fetch_transcript ranking).
    transcript_result = _fetch_transcript(video_id)
    if isinstance(transcript_result, IngestionError):
        return IngestionResult(success=False, error=transcript_result)

    segments, source_type, lang_code = transcript_result
    raw_text = _build_raw_text(segments)

    # 6. Fetch top comments (best-effort — None if disabled or errored)
    comments = await _fetch_top_comments(video_id)

    # 7. Persist
    tags = metadata.get("tags", [])
    video = existing_video or Video(
        youtube_id=video_id,
        url=url,
        title=metadata.get("title"),
        duration_sec=duration_sec,
        language=lang_code or detected_lang,
        thumbnail_url=metadata.get("thumbnail"),
        channel_name=metadata.get("channel"),
        channel_url=metadata.get("channel_url"),
        description=metadata.get("description"),
        upload_date=metadata.get("upload_date"),
        view_count=metadata.get("view_count"),
        like_count=metadata.get("like_count"),
        tags_json=json.dumps(tags) if tags else None,
        top_comments_json=json.dumps(comments) if comments else None,
        category=metadata.get("category"),
    )
    if not existing_video:
        session.add(video)
        await session.flush()  # get video.id

    quality_signal = (
        "auto_generated" if source_type == TranscriptSourceType.auto_generated else "good"
    )
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
