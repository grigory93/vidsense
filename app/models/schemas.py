from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# LLM output schemas (used with with_structured_output())
# ---------------------------------------------------------------------------


class ChapterSchema(BaseModel):
    """Canonical chapter structure required by the PRD."""

    chapter_id: str = Field(description="Unique identifier for this chapter, e.g. 'ch_01'")
    title: str = Field(description="Concise chapter heading")
    start_time_sec: int = Field(ge=0, description="Chapter start time in seconds")
    end_time_sec: int = Field(ge=1, description="Chapter end time in seconds")
    summary: str = Field(description="Short chapter summary")
    key_points: list[str] = Field(min_length=1, description="Array of key points from this chapter")
    transcript_segment: str = Field(description="Transcript text for this chapter")

    @model_validator(mode="after")
    def end_after_start(self) -> "ChapterSchema":
        if self.end_time_sec <= self.start_time_sec:
            raise ValueError(
                f"end_time_sec ({self.end_time_sec}) must be greater than "
                f"start_time_sec ({self.start_time_sec})"
            )
        return self


class ChapterListSchema(BaseModel):
    """Wrapper for LLM-returned chapter list."""

    chapters: list[ChapterSchema] = Field(min_length=1)


class SummarySchema(BaseModel):
    """Three-level summary structure."""

    thesis: str = Field(description="Short 1-sentence to 1-paragraph thesis / '1-minute' summary")
    executive: str = Field(description="Medium-length executive summary (several paragraphs)")
    detailed_outline: list[str] = Field(
        min_length=1, description="Detailed outline as array of structured points"
    )


# ---------------------------------------------------------------------------
# API response schemas
# ---------------------------------------------------------------------------


class AnalysisStatusSchema(BaseModel):
    run_id: int
    video_id: int
    status: Literal["pending", "processing", "complete", "partial", "failed"]
    summaries_ready: bool
    chapters_ready: bool
    error_message: str | None = None


class VideoMetaSchema(BaseModel):
    youtube_id: str
    title: str | None
    duration_sec: int | None
    thumbnail_url: str | None
    language: str | None


class ChapterResponseSchema(BaseModel):
    chapter_id: str
    title: str
    start_time_sec: int
    end_time_sec: int
    summary: str
    key_points: list[str]
    transcript_segment: str
    sort_order: int

    @property
    def start_time_display(self) -> str:
        return _seconds_to_mmss(self.start_time_sec)

    @property
    def end_time_display(self) -> str:
        return _seconds_to_mmss(self.end_time_sec)


class SummaryResponseSchema(BaseModel):
    level: Literal["thesis", "executive", "detailed"]
    content_text: str
    content_json: list[str] | None = None


class AnalyzeRequestSchema(BaseModel):
    url: str = Field(description="YouTube video URL")
    focus_prompt: str | None = Field(default=None, max_length=500, description="Optional global focus prompt")
    force_regenerate: bool = Field(default=False, description="If true, bypass cached run and rerun the LLM pipeline")

    @model_validator(mode="after")
    def sanitize_focus_prompt(self) -> "AnalyzeRequestSchema":
        if self.focus_prompt is not None:
            cleaned = self.focus_prompt.strip()
            # Treat very short or whitespace-only prompts as no focus
            self.focus_prompt = cleaned if len(cleaned) >= 3 else None
        return self


class RegenerateRequestSchema(BaseModel):
    focus_prompt: str | None = Field(default=None, max_length=500, description="Optional updated focus prompt")
    force_regenerate: bool = Field(default=False, description="If true, bypass cached run and rerun the LLM pipeline")

    @model_validator(mode="after")
    def sanitize_focus_prompt(self) -> "RegenerateRequestSchema":
        if self.focus_prompt is not None:
            cleaned = self.focus_prompt.strip()
            self.focus_prompt = cleaned if len(cleaned) >= 3 else None
        return self


# ---------------------------------------------------------------------------
# Internal typed error results (not HTTP errors — used within services)
# ---------------------------------------------------------------------------


class IngestionError(BaseModel):
    error_code: str
    message: str
    recoverable: bool = False


def _seconds_to_mmss(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
