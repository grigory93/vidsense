"""Tests for LangGraph pipeline nodes using a mocked LLM."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import ChapterListSchema, ChapterSchema, SummarySchema
from app.services.llm.nodes import (
    extract_chapters_node,
    gen_summaries_node,
    validate_input_node,
)
from app.services.llm.prompts import (
    chunk_segments,
    format_transcript_with_timestamps,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_transcript_source(raw_text: str = "Hello world.", segments: list | None = None):
    ts = MagicMock()
    ts.raw_text = raw_text
    ts.segments_json = json.dumps(segments or [])
    return ts


def _make_llm(return_value):
    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=return_value)
    llm.with_structured_output = MagicMock(return_value=structured)
    return llm


def _make_run():
    run = MagicMock()
    run.id = 1
    return run


def _make_session():
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# validate_input_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_input_passes_with_transcript():
    ts = _make_transcript_source("Some transcript text.")
    state = {"transcript_source": ts, "errors": []}
    result = await validate_input_node(state)
    assert result.get("pipeline_failed") is False


@pytest.mark.asyncio
async def test_validate_input_fails_without_transcript():
    state = {"transcript_source": None, "errors": []}
    result = await validate_input_node(state)
    assert result.get("pipeline_failed") is True
    assert len(result.get("errors", [])) > 0


@pytest.mark.asyncio
async def test_validate_input_fails_with_empty_transcript():
    ts = _make_transcript_source("   ")
    state = {"transcript_source": ts, "errors": []}
    result = await validate_input_node(state)
    assert result.get("pipeline_failed") is True


# ---------------------------------------------------------------------------
# gen_summaries_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gen_summaries_returns_result():
    expected = SummarySchema(
        thesis="A short thesis.",
        executive="An executive summary.",
        detailed_outline=["Point 1", "Point 2"],
    )
    llm = _make_llm(expected)
    ts = _make_transcript_source("Full transcript text here.")
    state = {
        "llm": llm,
        "transcript_source": ts,
        "focus_prompt": None,
        "pipeline_failed": False,
        "errors": [],
    }
    result = await gen_summaries_node(state)
    assert result["summary_result"] == expected
    assert result["summary_error"] is None


@pytest.mark.asyncio
async def test_gen_summaries_skips_when_pipeline_failed():
    state = {"pipeline_failed": True}
    result = await gen_summaries_node(state)
    assert result == {}


@pytest.mark.asyncio
async def test_gen_summaries_records_error_on_failure():
    from unittest.mock import AsyncMock, MagicMock
    from pydantic import ValidationError

    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
    llm.with_structured_output = MagicMock(return_value=structured)

    ts = _make_transcript_source("Some text.")
    state = {
        "llm": llm,
        "transcript_source": ts,
        "focus_prompt": None,
        "pipeline_failed": False,
        "errors": [],
    }
    result = await gen_summaries_node(state)
    assert result["summary_result"] is None
    assert result["summary_error"] is not None
    assert len(result["errors"]) > 0


# ---------------------------------------------------------------------------
# extract_chapters_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_chapters_returns_result():
    ch = ChapterSchema(
        chapter_id="ch_01",
        title="Intro",
        start_time_sec=0,
        end_time_sec=60,
        summary="S",
        key_points=["K"],
        transcript_segment="T",
    )
    expected = ChapterListSchema(chapters=[ch])
    llm = _make_llm(expected)
    ts = _make_transcript_source("Transcript.", segments=[{"text": "Hello", "start": 0, "duration": 5}])
    state = {
        "llm": llm,
        "transcript_source": ts,
        "focus_prompt": None,
        "pipeline_failed": False,
        "errors": [],
    }
    result = await extract_chapters_node(state)
    assert result["chapters_result"] == expected
    assert result["chapters_error"] is None


@pytest.mark.asyncio
async def test_extract_chapters_skips_when_pipeline_failed():
    state = {"pipeline_failed": True}
    result = await extract_chapters_node(state)
    assert result == {}


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def test_format_transcript_with_timestamps():
    segments = [
        {"text": "Hello", "start": 0, "duration": 2},
        {"text": "World", "start": 2, "duration": 2},
    ]
    result = format_transcript_with_timestamps(segments)
    assert "[0] Hello" in result
    assert "[2] World" in result


def test_chunk_segments_splits_large_transcript():
    # Create 20 segments of ~3000 chars each (~60k total)
    segments = [{"text": "x" * 3000, "start": i * 10, "duration": 10} for i in range(20)]
    chunks = chunk_segments(segments, max_chars=10_000, overlap_chars=500)
    assert len(chunks) > 1
    # Each chunk should be within the limit (allowing for overlap)
    for chunk in chunks:
        total = sum(len(s["text"]) for s in chunk)
        # With overlap, may slightly exceed, but should be reasonable
        assert total < 15_000


def test_chunk_segments_small_transcript_stays_single():
    segments = [{"text": "Short text.", "start": i, "duration": 1} for i in range(5)]
    chunks = chunk_segments(segments, max_chars=10_000)
    assert len(chunks) == 1
