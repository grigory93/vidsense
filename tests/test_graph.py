"""Tests for LangGraph pipeline nodes using a mocked LLM."""
from __future__ import annotations

import json
import operator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.models.schemas import (
    ChapterListSchema,
    ChapterSchema,
    GlossaryListSchema,
    GlossaryTermSchema,
    MindMapEdgeSchema,
    MindMapNodeSchema,
    MindMapSchema,
    SummarySchema,
)
from app.services.llm.nodes import (
    _find_term_occurrences,
    _invoke_with_structured_output,
    _is_permanent_api_error,
    embed_transcript_node,
    extract_chapters_node,
    extract_glossary_node,
    extract_mind_map_node,
    finalize_run_node,
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


def _make_session_factory():
    """Return an async context-manager factory yielding a mock DB session."""
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=execute_result)

    @asynccontextmanager
    async def factory():
        yield session

    return factory


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
    state = {"transcript_source": ts, "errors": [], "run_id": 1, "session_factory": _make_session_factory()}
    result = await validate_input_node(state)
    assert result.get("pipeline_failed") is False


@pytest.mark.asyncio
async def test_validate_input_fails_without_transcript():
    state = {"transcript_source": None, "errors": [], "run_id": 1, "session_factory": _make_session_factory()}
    result = await validate_input_node(state)
    assert result.get("pipeline_failed") is True
    assert len(result.get("errors", [])) > 0


@pytest.mark.asyncio
async def test_validate_input_fails_with_empty_transcript():
    ts = _make_transcript_source("   ")
    state = {"transcript_source": ts, "errors": [], "run_id": 1, "session_factory": _make_session_factory()}
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
        "transcript_source": ts,
        "focus_prompt": None,
        "pipeline_failed": False,
        "errors": [],
        "run_id": 1,
        "session_factory": _make_session_factory(),
    }
    with patch("app.services.llm.nodes.get_llm", return_value=llm):
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
    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
    llm.with_structured_output = MagicMock(return_value=structured)

    ts = _make_transcript_source("Some text.")
    state = {
        "transcript_source": ts,
        "focus_prompt": None,
        "pipeline_failed": False,
        "errors": [],
        "run_id": 1,
        "session_factory": _make_session_factory(),
    }
    with patch("app.services.llm.nodes.get_llm", return_value=llm):
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
        "transcript_source": ts,
        "focus_prompt": None,
        "pipeline_failed": False,
        "errors": [],
        "run_id": 1,
        "session_factory": _make_session_factory(),
    }
    with patch("app.services.llm.nodes.get_llm", return_value=llm):
        result = await extract_chapters_node(state)
    assert result["chapters_result"] == expected
    assert result["chapters_error"] is None


@pytest.mark.asyncio
async def test_extract_chapters_skips_when_pipeline_failed():
    state = {"pipeline_failed": True}
    result = await extract_chapters_node(state)
    assert result == {}


# ---------------------------------------------------------------------------
# extract_mind_map_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_mind_map_returns_result():
    nodes = [
        MindMapNodeSchema(
            node_id="n_01",
            label="Machine Learning",
            type="concept",
            description="ML is discussed in the intro.",
            chapter_ids=["ch_01"],
        ),
    ]
    edges = [
        MindMapEdgeSchema(source="n_01", target="n_02", relationship="uses"),
    ]
    expected = MindMapSchema(nodes=nodes, edges=edges)
    llm = _make_llm(expected)
    ts = _make_transcript_source("Transcript about ML.")
    state = {
        "transcript_source": ts,
        "focus_prompt": None,
        "pipeline_failed": False,
        "errors": [],
        "run_id": 1,
        "session_factory": _make_session_factory(),
        "chapters_result": ChapterListSchema(
            chapters=[
                ChapterSchema(
                    chapter_id="ch_01",
                    title="Intro",
                    start_time_sec=0,
                    end_time_sec=60,
                    summary="S",
                    key_points=["K"],
                    transcript_segment="T",
                ),
            ]
        ),
    }
    with patch("app.services.llm.nodes.get_llm", return_value=llm):
        result = await extract_mind_map_node(state)
    assert result["mind_map_result"] == expected
    assert result["mind_map_error"] is None


@pytest.mark.asyncio
async def test_extract_mind_map_skips_when_pipeline_failed():
    state = {"pipeline_failed": True}
    result = await extract_mind_map_node(state)
    assert result == {}


@pytest.mark.asyncio
async def test_extract_mind_map_records_error_on_failure():
    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
    llm.with_structured_output = MagicMock(return_value=structured)
    ts = _make_transcript_source("Some text.")
    state = {
        "transcript_source": ts,
        "pipeline_failed": False,
        "errors": [],
        "run_id": 1,
        "session_factory": _make_session_factory(),
    }
    with patch("app.services.llm.nodes.get_llm", return_value=llm):
        result = await extract_mind_map_node(state)
    assert result["mind_map_result"] is None
    assert result["mind_map_error"] is not None
    assert len(result["errors"]) > 0


# ---------------------------------------------------------------------------
# extract_glossary_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_glossary_returns_result():
    terms = [
        GlossaryTermSchema(
            term="API",
            definition="Application programming interface.",
            category="acronym",
            related_terms=[],
        ),
    ]
    expected = GlossaryListSchema(terms=terms)
    llm = _make_llm(expected)
    segments = [
        {"text": "We use the API here.", "start": 10, "duration": 2},
        {"text": "More content.", "start": 20, "duration": 2},
    ]
    ts = _make_transcript_source("Transcript.", segments=segments)
    state = {
        "transcript_source": ts,
        "focus_prompt": None,
        "pipeline_failed": False,
        "errors": [],
        "run_id": 1,
        "session_factory": _make_session_factory(),
    }
    with patch("app.services.llm.nodes.get_llm", return_value=llm):
        result = await extract_glossary_node(state)
    assert result["glossary_result"] == expected
    assert result["glossary_error"] is None


@pytest.mark.asyncio
async def test_extract_glossary_skips_when_pipeline_failed():
    state = {"pipeline_failed": True}
    result = await extract_glossary_node(state)
    assert result == {}


@pytest.mark.asyncio
async def test_extract_glossary_records_error_on_failure():
    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
    llm.with_structured_output = MagicMock(return_value=structured)
    ts = _make_transcript_source("Some text.")
    state = {
        "transcript_source": ts,
        "pipeline_failed": False,
        "errors": [],
        "run_id": 1,
        "session_factory": _make_session_factory(),
    }
    with patch("app.services.llm.nodes.get_llm", return_value=llm):
        result = await extract_glossary_node(state)
    assert result["glossary_result"] is None
    assert result["glossary_error"] is not None
    assert len(result["errors"]) > 0


# ---------------------------------------------------------------------------
# embed_transcript_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_transcript_skips_when_pipeline_failed():
    state = {"pipeline_failed": True}
    result = await embed_transcript_node(state)
    assert result == {}


@pytest.mark.asyncio
async def test_embed_transcript_returns_error_when_no_video_id():
    """When run has no video_id and DB lookup returns None, node returns embedding_error."""
    ts = _make_transcript_source("Some text.", segments=[{"text": "Hi", "start": 0, "duration": 1}])
    state = {
        "transcript_source": ts,
        "pipeline_failed": False,
        "run_id": 1,
        "run": None,
        "session_factory": _make_session_factory(),
    }
    result = await embed_transcript_node(state)
    assert result.get("embedding_error") is not None
    assert "video_id" in result["embedding_error"].lower() or "resolve" in result["embedding_error"].lower()


@pytest.mark.asyncio
async def test_embed_transcript_returns_error_when_no_transcript():
    """When segments are empty and raw_text is empty, node returns embedding_error."""
    ts = _make_transcript_source("   ", segments=[])
    run = MagicMock()
    run.video_id = 1
    state = {
        "transcript_source": ts,
        "pipeline_failed": False,
        "run_id": 1,
        "run": run,
        "session_factory": _make_session_factory(),
    }
    result = await embed_transcript_node(state)
    assert result.get("embedding_error") is not None
    assert "transcript" in result["embedding_error"].lower() or "no " in result["embedding_error"].lower()


# ---------------------------------------------------------------------------
# finalize_run_node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_run_sets_complete_when_summaries_and_chapters_ok():
    from app.models.db import AnalysisRunStatus

    run = MagicMock()
    run.id = 1
    run.video_id = 1
    run.status = None
    run.error_message = None
    run.completed_at = None
    run.current_step = "generating"
    session = MagicMock()
    session.commit = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none = MagicMock(return_value=run)
    session.execute = AsyncMock(return_value=execute_result)

    @asynccontextmanager
    async def factory():
        yield session

    state = {
        "run_id": 1,
        "session_factory": factory,
        "pipeline_failed": False,
        "summary_result": SummarySchema(
            thesis="T",
            executive="E",
            detailed_outline=["D"],
        ),
        "chapters_result": ChapterListSchema(
            chapters=[
                ChapterSchema(
                    chapter_id="ch_01",
                    title="Intro",
                    start_time_sec=0,
                    end_time_sec=60,
                    summary="S",
                    key_points=["K"],
                    transcript_segment="T",
                ),
            ]
        ),
        "summary_error": None,
        "chapters_error": None,
    }
    result = await finalize_run_node(state)
    assert result["final_status"] == AnalysisRunStatus.complete
    assert run.status == AnalysisRunStatus.complete
    assert run.completed_at is not None
    assert run.current_step is None


@pytest.mark.asyncio
async def test_finalize_run_sets_partial_when_only_summaries():
    from app.models.db import AnalysisRunStatus

    run = MagicMock()
    run.id = 1
    run.video_id = 1
    run.status = None
    run.error_message = None
    run.completed_at = None
    run.current_step = None
    session = MagicMock()
    session.commit = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none = MagicMock(return_value=run)
    session.execute = AsyncMock(return_value=execute_result)

    @asynccontextmanager
    async def factory():
        yield session

    state = {
        "run_id": 1,
        "session_factory": factory,
        "pipeline_failed": False,
        "summary_result": SummarySchema(
            thesis="T",
            executive="E",
            detailed_outline=["D"],
        ),
        "chapters_result": None,
        "summary_error": None,
        "chapters_error": "Chapter extraction failed.",
    }
    result = await finalize_run_node(state)
    assert result["final_status"] == AnalysisRunStatus.partial
    assert run.status == AnalysisRunStatus.partial
    assert run.error_message is not None
    assert "Chapter" in run.error_message


@pytest.mark.asyncio
async def test_finalize_run_sets_failed_when_pipeline_failed():
    from app.models.db import AnalysisRunStatus

    run = MagicMock()
    run.id = 1
    run.video_id = 1
    run.status = None
    run.error_message = None
    run.completed_at = None
    run.current_step = "failed"
    session = MagicMock()
    session.commit = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none = MagicMock(return_value=run)
    session.execute = AsyncMock(return_value=execute_result)

    @asynccontextmanager
    async def factory():
        yield session

    state = {
        "run_id": 1,
        "session_factory": factory,
        "pipeline_failed": True,
        "errors": ["No transcript available."],
    }
    result = await finalize_run_node(state)
    assert result["final_status"] == AnalysisRunStatus.failed
    assert run.status == AnalysisRunStatus.failed
    assert "No transcript" in (run.error_message or "")


@pytest.mark.asyncio
async def test_finalize_run_appends_v2_errors_to_error_message():
    """V2 feature errors are appended to error_message but do not change status."""
    from app.models.db import AnalysisRunStatus

    run = MagicMock()
    run.id = 1
    run.video_id = 1
    run.status = None
    run.error_message = None
    run.completed_at = None
    run.current_step = None
    session = MagicMock()
    session.commit = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none = MagicMock(return_value=run)
    session.execute = AsyncMock(return_value=execute_result)

    @asynccontextmanager
    async def factory():
        yield session

    state = {
        "run_id": 1,
        "session_factory": factory,
        "pipeline_failed": False,
        "summary_result": SummarySchema(
            thesis="T",
            executive="E",
            detailed_outline=["D"],
        ),
        "chapters_result": ChapterListSchema(
            chapters=[
                ChapterSchema(
                    chapter_id="ch_01",
                    title="Intro",
                    start_time_sec=0,
                    end_time_sec=60,
                    summary="S",
                    key_points=["K"],
                    transcript_segment="T",
                ),
            ]
        ),
        "summary_error": None,
        "chapters_error": None,
        "mind_map_error": "Mind map extraction failed.",
        "glossary_error": None,
        "embedding_error": "Embedding failed.",
    }
    result = await finalize_run_node(state)
    assert result["final_status"] == AnalysisRunStatus.complete
    assert run.status == AnalysisRunStatus.complete
    assert "Mind map" in (run.error_message or "")
    assert "Embedding" in (run.error_message or "")


# ---------------------------------------------------------------------------
# _find_term_occurrences
# ---------------------------------------------------------------------------


def test_find_term_occurrences_exact_match():
    segments = [
        {"text": "Hello world", "start": 0, "duration": 2},
        {"text": "The API is used here.", "start": 10, "duration": 3},
        {"text": "More text.", "start": 20, "duration": 1},
    ]
    result = _find_term_occurrences("API", segments)
    assert len(result) == 1
    assert result[0]["timestamp_sec"] == 10
    assert "display" in result[0]


def test_find_term_occurrences_empty_segments():
    assert _find_term_occurrences("term", []) == []


def test_find_term_occurrences_multi_word_span():
    """Multi-word term can span consecutive segments (sliding window or stem match)."""
    segments = [
        {"text": "We discuss", "start": 0, "duration": 1},
        {"text": "neural network", "start": 5, "duration": 2},
        {"text": "architecture.", "start": 10, "duration": 1},
    ]
    result = _find_term_occurrences("neural network architecture", segments)
    assert len(result) >= 1
    # Implementation may attribute to first segment of matching window (0) or segment start (5)
    assert result[0]["timestamp_sec"] in (0, 5)


def test_find_term_occurrences_stem_match():
    """Stem-based match: 'algorithm' matches segment containing 'algorithms'."""
    segments = [
        {"text": "Algorithms are important.", "start": 30, "duration": 2},
    ]
    result = _find_term_occurrences("algorithm", segments)
    assert len(result) == 1
    assert result[0]["timestamp_sec"] == 30


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


# ---------------------------------------------------------------------------
# _is_permanent_api_error
# ---------------------------------------------------------------------------


def test_is_permanent_api_error_detects_quota():
    assert _is_permanent_api_error(Exception("insufficient_quota")) is True


def test_is_permanent_api_error_detects_invalid_key():
    assert _is_permanent_api_error(Exception("invalid_api_key")) is True


def test_is_permanent_api_error_detects_google_invalid_key():
    # Google surfaces invalid API keys as 'api_key_invalid' in the error body
    assert _is_permanent_api_error(
        Exception("400 API key not valid. Please pass a valid API key. [api_key_invalid]")
    ) is True


def test_is_permanent_api_error_detects_anthropic_billing():
    # Anthropic surfaces billing exhaustion with this specific phrase
    assert _is_permanent_api_error(
        Exception("Your credit balance is too low to access the Anthropic API.")
    ) is True


def test_is_permanent_api_error_false_for_google_rate_limit():
    # Google resource_exhausted is used for transient rate limits — must NOT fast-fail
    assert _is_permanent_api_error(Exception("resource_exhausted")) is False


def test_is_permanent_api_error_false_for_rate_limit():
    # rate_limit_exceeded is transient — should NOT be treated as permanent
    assert _is_permanent_api_error(Exception("rate_limit_exceeded")) is False


def test_is_permanent_api_error_false_for_generic():
    assert _is_permanent_api_error(Exception("connection timeout")) is False


def test_is_permanent_api_error_case_insensitive():
    assert _is_permanent_api_error(Exception("Insufficient_Quota error")) is True


# ---------------------------------------------------------------------------
# _invoke_with_structured_output — quota fast-fail and backoff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoke_quota_error_does_not_retry():
    """insufficient_quota breaks immediately without sleeping or retrying."""
    quota_exc = Exception(
        "Error code: 429 - {'error': {'code': 'insufficient_quota'}}"
    )
    structured = MagicMock()
    structured.ainvoke = AsyncMock(side_effect=quota_exc)
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)

    with patch("app.services.llm.nodes.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result, error = await _invoke_with_structured_output(llm, MagicMock(), [], max_retries=2)

    # Only called once (no retries)
    assert structured.ainvoke.call_count == 1
    mock_sleep.assert_not_called()
    assert result is None
    assert "insufficient_quota" in (error or "")


@pytest.mark.asyncio
async def test_invoke_transient_error_sleeps_between_retries():
    """Transient errors sleep 2^attempt seconds before each retry."""
    transient_exc = Exception("connection timeout")
    structured = MagicMock()
    structured.ainvoke = AsyncMock(side_effect=transient_exc)
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)

    with patch("app.services.llm.nodes.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result, error = await _invoke_with_structured_output(llm, MagicMock(), [], max_retries=2)

    assert structured.ainvoke.call_count == 3  # initial + 2 retries
    assert mock_sleep.call_count == 2
    # Exponential: sleep(1) then sleep(2)
    mock_sleep.assert_any_call(1)
    mock_sleep.assert_any_call(2)
    assert result is None


@pytest.mark.asyncio
async def test_invoke_succeeds_on_second_attempt():
    """Succeeds on the second attempt after a transient failure."""
    from pydantic import BaseModel

    class DummySchema(BaseModel):
        value: str

    expected = DummySchema(value="ok")
    structured = MagicMock()
    structured.ainvoke = AsyncMock(
        side_effect=[Exception("connection reset"), expected]
    )
    llm = MagicMock()
    llm.with_structured_output = MagicMock(return_value=structured)

    with patch("app.services.llm.nodes.asyncio.sleep", new_callable=AsyncMock):
        result, error = await _invoke_with_structured_output(llm, DummySchema, [], max_retries=2)

    assert result == expected
    assert error is None
    assert structured.ainvoke.call_count == 2


# ---------------------------------------------------------------------------
# LangGraph errors reducer (Annotated[list, operator.add])
# ---------------------------------------------------------------------------


def test_errors_reducer_combines_lists():
    """operator.add is the LangGraph reducer for GraphState.errors.
    Parallel nodes returning separate error lists must be concatenated, not overwritten."""
    errors_a = ["Summary generation failed: timeout"]
    errors_b = ["Chapter extraction failed: timeout"]
    combined = operator.add(errors_a, errors_b)
    assert combined == [
        "Summary generation failed: timeout",
        "Chapter extraction failed: timeout",
    ]


def test_errors_reducer_with_empty_initial():
    assert operator.add([], ["some error"]) == ["some error"]


def test_errors_reducer_with_empty_update():
    assert operator.add(["existing"], []) == ["existing"]


@pytest.mark.asyncio
async def test_parallel_nodes_errors_do_not_overwrite_each_other():
    """When two pipeline nodes both fail, both errors appear in the final accumulated list.

    Simulates what LangGraph does: each node returns {"errors": [...]}, and the
    reducer (operator.add) appends rather than replaces.
    """
    llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
    llm.with_structured_output = MagicMock(return_value=structured)

    ts = _make_transcript_source("Some text.")
    base_state = {
        "transcript_source": ts,
        "focus_prompt": None,
        "pipeline_failed": False,
        "run_id": 1,
        "session_factory": _make_session_factory(),
    }

    with patch("app.services.llm.nodes.get_llm", return_value=llm):
        summary_result = await gen_summaries_node(base_state)
        mind_map_result = await extract_mind_map_node(base_state)

    # Each node returns its own error list
    assert len(summary_result["errors"]) > 0
    assert len(mind_map_result["errors"]) > 0

    # The reducer combines them
    accumulated = operator.add(summary_result["errors"], mind_map_result["errors"])
    assert len(accumulated) == 2
