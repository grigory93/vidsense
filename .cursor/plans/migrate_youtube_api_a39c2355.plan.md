---
name: Migrate YouTube API
overview: Replace yt-dlp with the official YouTube Data API v3 for metadata, add video tags/category/comments as LLM context, fix upload_date format, update language detection, and retain youtube-transcript-api for transcripts.
todos:
  - id: config-and-deps
    content: Add youtube settings to config.py / .env.example; remove yt-dlp from pyproject.toml
    status: completed
  - id: db-schema
    content: Add tags_json, top_comments_json, category to Video model + migration entries in database.py
    status: completed
  - id: youtube-service
    content: Replace _fetch_metadata with async httpx calls to Data API v3 (videos.list + commentThreads.list); update _detect_language; add ISO 8601 duration parser
    status: completed
  - id: upload-date-migration
    content: Store ISO 8601 publishedAt; update video_metadata.html template to parse both old YYYYMMDD and new ISO formats
    status: completed
  - id: llm-context
    content: Add video_tags/video_comments/video_category to GraphState; inject into summary and chapter prompts
    status: completed
  - id: tests
    content: "Rewrite test_youtube.py: replace yt-dlp mocks with httpx mocks; add ISO 8601 duration parser tests; add _detect_language tests for new API fields"
    status: completed
isProject: false
---

# Migrate YouTube Integration to Official API v3

Replace the unofficial `yt-dlp` scraper (which triggers bot-detection on cloud/VM IPs) with the official YouTube Data API v3 for all metadata. Retain `youtube-transcript-api` for transcripts (the official Captions API requires OAuth2 as the video owner). Enrich LLM context with video tags, category, and top comments.

## Key Design Decisions

- **API key required at startup** -- app refuses to start without `YOUTUBE_API_KEY` (same pattern as `APP_SECRET_KEY`).
- `**upload_date` stored as ISO 8601** going forward; template updated to handle both old `YYYYMMDD` rows and new ISO strings.
- **Comments are best-effort** -- silently store `null` if disabled on a video (no user-visible warning).
- **Comment injection into LLM prompts is configurable** via `youtube_max_comments` and `youtube_max_comment_chars` settings to control token budget.
- **Video category** captured from `snippet.categoryId` (resolved to display name) for LLM domain hints.
- **Language detection** uses `snippet.defaultAudioLanguage` (more reliable than yt-dlp's heuristic).

## 1. Configuration and Dependencies

**[app/config.py](app/config.py)** -- add to `Settings`:

- `youtube_api_key: str` (required, validated non-empty; app refuses to start if missing)
- `youtube_max_comments: int = 20` (how many top comments to fetch)
- `youtube_max_comment_chars: int = 300` (per-comment truncation limit)

**[.env.example](.env.example)** -- add `YOUTUBE_API_KEY=...` in a new "YouTube" section.

**[pyproject.toml](pyproject.toml)** -- remove `yt-dlp` from `[project.dependencies]`. `httpx` is already present.

## 2. Database Schema

**[app/models/db.py](app/models/db.py)** -- add to `Video`:

- `tags_json: Mapped[str | None] = mapped_column(Text)` -- JSON array of creator tags
- `top_comments_json: Mapped[str | None] = mapped_column(Text)` -- JSON array of `{author, text}` dicts
- `category: Mapped[str | None] = mapped_column(String(128))` -- resolved category name (e.g., "Education")

**[app/database.py](app/database.py)** -- add migration entries to `_add_missing_columns`:

```python
("videos", "tags_json", "TEXT"),
("videos", "top_comments_json", "TEXT"),
("videos", "category", "VARCHAR(128)"),
```

Note: existing `upload_date` column is `String(20)` which is too short for ISO 8601 (`2024-01-15T12:00:00Z` = 20 chars). It fits exactly, but to be safe we should keep the existing column type since 20 chars accommodates the format.

## 3. YouTube Service ([app/services/youtube.py](app/services/youtube.py))

**Remove:** `import yt_dlp`, `_YDL_OPTS` dict, existing `_fetch_metadata()` function.

**Add `_fetch_metadata(video_id)` (async):**

- Call `https://www.googleapis.com/youtube/v3/videos?id={video_id}&part=snippet,contentDetails,statistics&key={api_key}` via `httpx.AsyncClient`.
- Map response fields to a dict matching the keys `ingest_video` already uses:
  - `title` from `snippet.title`
  - `description` from `snippet.description`
  - `thumbnail` from `snippet.thumbnails.high.url` (fallback: `.medium.url`, `.default.url`)
  - `uploader` / `channel` from `snippet.channelTitle`
  - `channel_url` from `https://www.youtube.com/channel/{snippet.channelId}`
  - `upload_date` from `snippet.publishedAt` (ISO 8601, stored as-is)
  - `duration` parsed from `contentDetails.duration` (ISO 8601 period, e.g., `PT1H2M3S` -> seconds)
  - `view_count` from `statistics.viewCount` (int)
  - `like_count` from `statistics.likeCount` (int)
  - `tags` from `snippet.tags` (list of strings, stored as JSON)
  - `category` resolved from `snippet.categoryId` via `videoCategories.list` or a static lookup map
  - `language` from `snippet.defaultAudioLanguage` (fallback: `snippet.defaultLanguage`)
- Return `IngestionError(error_code="METADATA_FETCH_FAILED", ...)` on HTTP errors or empty `items[]`.

**Add `_parse_iso8601_duration(iso_str)` helper:**

- Parse `PT(\d+H)?(\d+M)?(\d+S)?` -> total seconds. Handle edge cases (`P0D`, `PT0S`, missing components).

**Update `_detect_language(info)`:**

- Primary: read `language` key (now populated from `snippet.defaultAudioLanguage`).
- Fallback: keep existing subtitles/captions heuristic for backward compatibility with cached data.

**Add `_fetch_top_comments(video_id)` (async):**

- Call `https://www.googleapis.com/youtube/v3/commentThreads?videoId={video_id}&part=snippet&order=relevance&maxResults={settings.youtube_max_comments}&key={api_key}`.
- Extract `{author, text}` from each `snippet.topLevelComment.snippet`.
- Truncate each `text` to `settings.youtube_max_comment_chars`.
- On 403 `commentsDisabled` or any error: return `None` silently (best-effort).

**Update `ingest_video()`:**

- Change `_fetch_metadata` call to `await _fetch_metadata(video_id)` (now async -- no thread executor needed).
- After metadata, call `await _fetch_top_comments(video_id)`.
- Store `tags_json`, `top_comments_json`, and `category` on the `Video` object.

## 4. Upload Date Template Fix

**[app/templates/partials/video_metadata.html](app/templates/partials/video_metadata.html)** (lines 56-64):

- Update the Jinja2 date formatting block to handle both:
  - Legacy `YYYYMMDD` (8 chars, existing DB rows)
  - New ISO 8601 `YYYY-MM-DDTHH:MM:SSZ` (contains `-` and `T`)
- Detection: if `yd` contains `T`, parse as ISO 8601; else use existing `length == 8` logic.

## 5. LLM Context Enhancements

**[app/services/llm/state.py](app/services/llm/state.py)** -- add to `GraphState`:

- `video_tags: Any` -- `list[str] | None`
- `video_comments: Any` -- `list[dict] | None`
- `video_category: Any` -- `str | None`

**[app/services/llm/graph.py](app/services/llm/graph.py)** -- in `run_pipeline()`, populate new state keys from `Video` model fields (parse `tags_json` and `top_comments_json` from JSON).

**[app/services/llm/prompts.py](app/services/llm/prompts.py)** -- add a `<video_context>` block injected into summary and chapter system prompts when tags/comments/category are available:

```
<video_context>
Category: {category}
Creator tags: {comma-separated tags}
Top viewer comments (for audience sentiment context):
- "{comment_1}"
- "{comment_2}"
...
</video_context>
```

Only include sections that have data. This block is appended after the existing system prompt and before any `<user_focus>` block.

## 6. Testing

**[tests/test_youtube.py](tests/test_youtube.py)**:

- Remove all `yt-dlp` mock references.
- Add `TestFetchMetadata` class: mock `httpx.AsyncClient.get` to return sample `videos.list` JSON; verify field mapping, error handling for 403/404, empty items array.
- Add `TestParseIsoDuration`: cover `PT1H2M3S`, `PT5M`, `PT30S`, `P0D`, `PT0S`, malformed strings.
- Update `TestDetectLanguage`: test with new `defaultAudioLanguage`-style data.
- Add `TestFetchTopComments`: mock `commentThreads.list` response; verify truncation; verify graceful handling of `commentsDisabled` 403.

## Risks and Mitigations

- **YouTube Data API v3 quota**: Default is 10,000 units/day. `videos.list` = 1 unit, `commentThreads.list` = 1 unit. At 2 units per video analyzed, this supports ~5,000 videos/day. Monitor via GCP console; request quota increase if needed.
- `**youtube-transcript-api` may also face throttling on datacenter IPs**: Less aggressive than yt-dlp but still possible. If this becomes an issue, a future enhancement could add configurable proxy support or cookie injection specifically for the transcript library.
- **Cached videos with old yt-dlp data**: Existing DB rows will have `YYYYMMDD` upload dates, no tags/comments/category. The template and LLM prompts must handle `null` gracefully (already addressed above).

