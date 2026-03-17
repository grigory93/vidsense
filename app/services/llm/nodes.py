"""
LangGraph node implementations for the VidSense processing pipeline.

Each function takes the current GraphState and returns a partial state update.

IMPORTANT: gen_summaries_node and extract_chapters_node run in parallel (LangGraph
fan-out). They must never share a single AsyncSession — concurrent commits on the same
session raise InvalidRequestError. Each node opens its own short-lived session via the
session_factory stored in GraphState.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from langchain_core.language_models import BaseChatModel
from pydantic import ValidationError
from sqlalchemy import select

from app.config import settings
from app.models.db import (
    AnalysisRun,
    AnalysisRunStatus,
    Chapter,
    Summary,
    SummaryLevel,
)
from app.models.schemas import ChapterListSchema, SummarySchema
from app.services.llm.prompts import (
    build_chapter_messages,
    build_chapter_messages_chunk,
    build_summary_messages,
    chunk_segments,
    format_transcript_with_timestamps,
)
from app.services.llm.state import GraphState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CHAR_THRESHOLD_FOR_CHUNKING = 40_000  # ~30-40 min of typical speech


async def _invoke_with_structured_output(
    llm: BaseChatModel,
    schema: type,
    messages: list,
    max_retries: int,
) -> tuple[object | None, str | None]:
    """
    Call llm.with_structured_output(schema) with retry on ValidationError.
    Returns (result, error_message).
    """
    structured_llm = llm.with_structured_output(schema)
    last_error: str | None = None

    for attempt in range(max_retries + 1):
        try:
            result = await structured_llm.ainvoke(messages)
            return result, None
        except ValidationError as exc:
            last_error = str(exc)
            logger.warning("Structured output validation failed (attempt %d): %s", attempt + 1, exc)
            if attempt < max_retries:
                from langchain_core.messages import HumanMessage

                feedback = (
                    f"Your previous response failed schema validation: {exc}. "
                    "Please correct the output and try again."
                )
                messages = messages + [HumanMessage(content=feedback)]
        except Exception as exc:
            last_error = str(exc)
            logger.error("LLM invocation error (attempt %d): %s", attempt + 1, exc)
            if attempt < max_retries:
                continue
            break

    return None, last_error


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


async def _set_step(state: GraphState, step: str) -> None:
    """Persist current_step to DB using a fresh session (safe for parallel nodes)."""
    session_factory = state["session_factory"]
    run_id: int = state["run_id"]
    async with session_factory() as sess:
        result = await sess.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
        db_run = result.scalar_one_or_none()
        if db_run:
            db_run.current_step = step
            await sess.commit()


async def validate_input_node(state: GraphState) -> dict:
    """Confirm transcript is present and well-formed before LLM processing."""
    run_id: int = state["run_id"]
    logger.info("[run=%d] validate_input: checking transcript", run_id)

    transcript_source = state.get("transcript_source")
    if not transcript_source or not transcript_source.raw_text.strip():
        logger.error("[run=%d] validate_input: no transcript — aborting pipeline", run_id)
        await _set_step(state, "failed")
        return {
            "errors": state.get("errors", []) + ["No transcript available for processing."],
            "pipeline_failed": True,
        }

    char_count = len(transcript_source.raw_text)
    logger.info(
        "[run=%d] validate_input: transcript OK — %d chars, source_type=%s",
        run_id, char_count, transcript_source.source_type,
    )
    await _set_step(state, "generating")
    return {"pipeline_failed": False}


async def gen_summaries_node(state: GraphState) -> dict:
    """Generate 3-level summaries from the transcript and persist immediately."""
    if state.get("pipeline_failed"):
        return {}

    run_id: int = state["run_id"]
    session_factory = state["session_factory"]
    llm: BaseChatModel = state["llm"]
    transcript_source = state["transcript_source"]
    focus_prompt = state.get("focus_prompt")

    char_count = len(transcript_source.raw_text)
    logger.info("[run=%d] gen_summaries: starting — transcript %d chars", run_id, char_count)

    await _set_step(state, "generating_summaries")

    transcript_text = transcript_source.raw_text
    messages = build_summary_messages(transcript_text, focus_prompt)

    logger.info("[run=%d] gen_summaries: invoking LLM for 3-level summary", run_id)
    result, error = await _invoke_with_structured_output(
        llm, SummarySchema, messages, settings.llm_max_retries
    )

    if result is None:
        logger.error("[run=%d] gen_summaries: FAILED — %s", run_id, error)
        return {
            "summary_result": None,
            "summary_error": error or "Summary generation failed.",
            "errors": state.get("errors", []) + [f"Summary generation failed: {error}"],
        }

    level_map = [
        (SummaryLevel.thesis, result.thesis, None),
        (SummaryLevel.executive, result.executive, None),
        (
            SummaryLevel.detailed,
            "\n".join(result.detailed_outline),
            json.dumps(result.detailed_outline),
        ),
    ]

    async with session_factory() as sess:
        for level, text, content_json in level_map:
            summary = Summary(
                run_id=run_id,
                level=level,
                content_text=text,
                content_json=content_json,
            )
            sess.add(summary)
        await sess.commit()

    logger.info("[run=%d] gen_summaries: done and persisted", run_id)
    return {"summary_result": result, "summary_error": None}


async def extract_chapters_node(state: GraphState) -> dict:
    """Extract smart chapters from the transcript and persist immediately (chunk-by-chunk for long videos)."""
    if state.get("pipeline_failed"):
        return {}

    run_id: int = state["run_id"]
    session_factory = state["session_factory"]
    llm: BaseChatModel = state["llm"]
    transcript_source = state["transcript_source"]
    focus_prompt = state.get("focus_prompt")

    segments: list[dict] = []
    if transcript_source.segments_json:
        try:
            segments = json.loads(transcript_source.segments_json)
        except (json.JSONDecodeError, TypeError):
            segments = []

    raw_len = len(transcript_source.raw_text)
    logger.info(
        "[run=%d] extract_chapters: starting — transcript %d chars, %d segments",
        run_id, raw_len, len(segments),
    )

    await _set_step(state, "extracting_chapters")

    if raw_len <= _CHAR_THRESHOLD_FOR_CHUNKING or not segments:
        logger.info("[run=%d] extract_chapters: single-pass extraction", run_id)
        formatted = format_transcript_with_timestamps(segments) if segments else transcript_source.raw_text
        messages = build_chapter_messages(formatted, focus_prompt)
        result, error = await _invoke_with_structured_output(
            llm, ChapterListSchema, messages, settings.llm_max_retries
        )
        if result is None:
            logger.error("[run=%d] extract_chapters: FAILED — %s", run_id, error)
            return {
                "chapters_result": None,
                "chapters_error": error or "Chapter extraction failed.",
                "errors": state.get("errors", []) + [f"Chapter extraction failed: {error}"],
            }

        async with session_factory() as sess:
            for idx, ch in enumerate(result.chapters):
                chapter = Chapter(
                    run_id=run_id,
                    chapter_id=ch.chapter_id,
                    title=ch.title,
                    start_time_sec=ch.start_time_sec,
                    end_time_sec=ch.end_time_sec,
                    summary=ch.summary,
                    key_points_json=json.dumps(ch.key_points),
                    transcript_segment=ch.transcript_segment,
                    sort_order=idx,
                )
                sess.add(chapter)
            await sess.commit()

        logger.info("[run=%d] extract_chapters: done and persisted — %d chapters", run_id, len(result.chapters))
        return {"chapters_result": result, "chapters_error": None}

    # Chunked extraction for long transcripts — persist each chunk as it completes
    all_chapters: list = []
    all_chapter_ids: set[str] = set()
    sort_offset = 0
    chunks = chunk_segments(segments)
    total = len(chunks)
    logger.info("[run=%d] extract_chapters: chunked extraction — %d chunks", run_id, total)

    for i, chunk in enumerate(chunks):
        start_sec = int(chunk[0].get("start", 0))
        end_sec = int(chunk[-1].get("start", 0) + chunk[-1].get("duration", 0))
        start_str = _sec_to_hms(start_sec)
        end_str = _sec_to_hms(end_sec)
        await _set_step(state, f"chapters_chunk_{i + 1}_of_{total}")
        logger.info(
            "[run=%d] extract_chapters: chunk %d/%d (%s → %s)",
            run_id, i + 1, total, start_str, end_str,
        )
        formatted_chunk = format_transcript_with_timestamps(chunk)
        messages = build_chapter_messages_chunk(
            formatted_chunk, i + 1, total, start_str, end_str, focus_prompt
        )
        result, error = await _invoke_with_structured_output(
            llm, ChapterListSchema, messages, settings.llm_max_retries
        )
        if result is None:
            logger.warning("[run=%d] extract_chapters: chunk %d/%d FAILED — %s", run_id, i + 1, total, error)
            continue

        new_chapters = []
        for ch in result.chapters:
            if ch.chapter_id not in all_chapter_ids:
                all_chapter_ids.add(ch.chapter_id)
                new_chapters.append(ch)

        new_chapters.sort(key=lambda c: c.start_time_sec)

        async with session_factory() as sess:
            for j, ch in enumerate(new_chapters):
                chapter = Chapter(
                    run_id=run_id,
                    chapter_id=ch.chapter_id,
                    title=ch.title,
                    start_time_sec=ch.start_time_sec,
                    end_time_sec=ch.end_time_sec,
                    summary=ch.summary,
                    key_points_json=json.dumps(ch.key_points),
                    transcript_segment=ch.transcript_segment,
                    sort_order=sort_offset + j,
                )
                sess.add(chapter)
            await sess.commit()

        sort_offset += len(new_chapters)
        all_chapters.extend(new_chapters)
        logger.info("[run=%d] extract_chapters: chunk %d/%d done and persisted — %d chapters", run_id, i + 1, total, len(new_chapters))

    if not all_chapters:
        logger.error("[run=%d] extract_chapters: all chunks FAILED", run_id)
        return {
            "chapters_result": None,
            "chapters_error": "Chapter extraction failed for all transcript chunks.",
            "errors": state.get("errors", []) + ["Chapter extraction failed."],
        }

    all_chapters.sort(key=lambda c: c.start_time_sec)
    logger.info("[run=%d] extract_chapters: done — %d chapters total", run_id, len(all_chapters))

    merged = ChapterListSchema(chapters=all_chapters)
    return {"chapters_result": merged, "chapters_error": None}


async def finalize_run_node(state: GraphState) -> dict:
    """Set final run status and completion timestamp based on what was persisted."""
    run_id: int = state["run_id"]
    session_factory = state["session_factory"]
    logger.info("[run=%d] finalize_run: setting final status", run_id)

    summary_result: SummarySchema | None = state.get("summary_result")
    chapters_result: ChapterListSchema | None = state.get("chapters_result")
    summary_error: str | None = state.get("summary_error")
    chapters_error: str | None = state.get("chapters_error")
    pipeline_failed: bool = state.get("pipeline_failed", False)

    async with session_factory() as sess:
        result = await sess.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
        run = result.scalar_one_or_none()
        if run is None:
            logger.error("[run=%d] finalize_run: run not found in DB", run_id)
            return {"final_status": AnalysisRunStatus.failed}

        if pipeline_failed:
            run.status = AnalysisRunStatus.failed
            run.error_message = "; ".join(state.get("errors", ["Pipeline failed."]))
            run.completed_at = datetime.now(timezone.utc)
            run.current_step = None
            await sess.commit()
            return {"final_status": AnalysisRunStatus.failed}

        has_summaries = summary_result is not None
        has_chapters = chapters_result is not None

        if has_summaries and has_chapters:
            final_status = AnalysisRunStatus.complete
        elif has_summaries or has_chapters:
            final_status = AnalysisRunStatus.partial
            errors = []
            if summary_error:
                errors.append(f"Summaries: {summary_error}")
            if chapters_error:
                errors.append(f"Chapters: {chapters_error}")
            run.error_message = "; ".join(errors)
        else:
            final_status = AnalysisRunStatus.failed
            run.error_message = "; ".join(state.get("errors", ["All pipeline stages failed."]))

        run.status = final_status
        run.current_step = None
        run.completed_at = datetime.now(timezone.utc)
        await sess.commit()

    logger.info(
        "[run=%d] finalize_run: done — final_status=%s summaries=%s chapters=%s",
        run_id, final_status,
        "ok" if summary_result else f"error({summary_error})",
        "ok" if chapters_result else f"error({chapters_error})",
    )
    return {"final_status": final_status}


def _sec_to_hms(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
