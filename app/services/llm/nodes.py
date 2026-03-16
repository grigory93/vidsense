"""
LangGraph node implementations for the VidSense processing pipeline.

Each function takes the current GraphState and returns a partial state update.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from langchain_core.language_models import BaseChatModel
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.db import (
    AnalysisRun,
    AnalysisRunStatus,
    Chapter,
    Summary,
    SummaryLevel,
    TranscriptSourceType,
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
                # Append corrective feedback to messages
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
    """Persist current_step to DB so the UI can reflect progress."""
    session: AsyncSession = state["session"]
    run: AnalysisRun = state["run"]
    run.current_step = step
    await session.commit()


async def validate_input_node(state: GraphState) -> dict:
    """Confirm transcript is present and well-formed before LLM processing."""
    run: AnalysisRun = state["run"]
    logger.info("[run=%d] validate_input: checking transcript", run.id)

    transcript_source = state.get("transcript_source")
    if not transcript_source or not transcript_source.raw_text.strip():
        logger.error("[run=%d] validate_input: no transcript — aborting pipeline", run.id)
        await _set_step(state, "failed")
        return {
            "errors": state.get("errors", []) + ["No transcript available for processing."],
            "pipeline_failed": True,
        }

    char_count = len(transcript_source.raw_text)
    logger.info(
        "[run=%d] validate_input: transcript OK — %d chars, source_type=%s",
        run.id, char_count, transcript_source.source_type,
    )
    await _set_step(state, "generating")
    return {"pipeline_failed": False}


async def gen_summaries_node(state: GraphState) -> dict:
    """Generate 3-level summaries from the transcript."""
    if state.get("pipeline_failed"):
        return {}

    run: AnalysisRun = state["run"]
    llm: BaseChatModel = state["llm"]
    transcript_source = state["transcript_source"]
    focus_prompt = state.get("focus_prompt")

    char_count = len(transcript_source.raw_text)
    logger.info("[run=%d] gen_summaries: starting — transcript %d chars", run.id, char_count)

    transcript_text = transcript_source.raw_text
    messages = build_summary_messages(transcript_text, focus_prompt)

    logger.info("[run=%d] gen_summaries: invoking LLM for 3-level summary", run.id)
    result, error = await _invoke_with_structured_output(
        llm, SummarySchema, messages, settings.llm_max_retries
    )

    if result is None:
        logger.error("[run=%d] gen_summaries: FAILED — %s", run.id, error)
        return {
            "summary_result": None,
            "summary_error": error or "Summary generation failed.",
            "errors": state.get("errors", []) + [f"Summary generation failed: {error}"],
        }

    logger.info("[run=%d] gen_summaries: done", run.id)
    return {"summary_result": result, "summary_error": None}


async def extract_chapters_node(state: GraphState) -> dict:
    """Extract smart chapters from the transcript."""
    if state.get("pipeline_failed"):
        return {}

    run: AnalysisRun = state["run"]
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
        run.id, raw_len, len(segments),
    )

    if raw_len <= _CHAR_THRESHOLD_FOR_CHUNKING or not segments:
        logger.info("[run=%d] extract_chapters: single-pass extraction", run.id)
        formatted = format_transcript_with_timestamps(segments) if segments else transcript_source.raw_text
        messages = build_chapter_messages(formatted, focus_prompt)
        result, error = await _invoke_with_structured_output(
            llm, ChapterListSchema, messages, settings.llm_max_retries
        )
        if result is None:
            logger.error("[run=%d] extract_chapters: FAILED — %s", run.id, error)
            return {
                "chapters_result": None,
                "chapters_error": error or "Chapter extraction failed.",
                "errors": state.get("errors", []) + [f"Chapter extraction failed: {error}"],
            }
        logger.info("[run=%d] extract_chapters: done — %d chapters", run.id, len(result.chapters))
        return {"chapters_result": result, "chapters_error": None}

    # Chunked extraction for long transcripts
    all_chapters = []
    chunks = chunk_segments(segments)
    total = len(chunks)
    logger.info("[run=%d] extract_chapters: chunked extraction — %d chunks", run.id, total)

    for i, chunk in enumerate(chunks):
        start_sec = int(chunk[0].get("start", 0))
        end_sec = int(chunk[-1].get("start", 0) + chunk[-1].get("duration", 0))
        start_str = _sec_to_hms(start_sec)
        end_str = _sec_to_hms(end_sec)
        logger.info(
            "[run=%d] extract_chapters: chunk %d/%d (%s → %s)",
            run.id, i + 1, total, start_str, end_str,
        )
        formatted_chunk = format_transcript_with_timestamps(chunk)
        messages = build_chapter_messages_chunk(
            formatted_chunk, i + 1, total, start_str, end_str, focus_prompt
        )
        result, error = await _invoke_with_structured_output(
            llm, ChapterListSchema, messages, settings.llm_max_retries
        )
        if result is None:
            logger.warning("[run=%d] extract_chapters: chunk %d/%d FAILED — %s", run.id, i + 1, total, error)
            continue
        logger.info("[run=%d] extract_chapters: chunk %d/%d done — %d chapters", run.id, i + 1, total, len(result.chapters))
        all_chapters.extend(result.chapters)

    if not all_chapters:
        logger.error("[run=%d] extract_chapters: all chunks FAILED", run.id)
        return {
            "chapters_result": None,
            "chapters_error": "Chapter extraction failed for all transcript chunks.",
            "errors": state.get("errors", []) + ["Chapter extraction failed."],
        }

    # Deduplicate by chapter_id, keep first occurrence
    seen: set[str] = set()
    deduped = []
    for ch in all_chapters:
        if ch.chapter_id not in seen:
            seen.add(ch.chapter_id)
            deduped.append(ch)

    deduped.sort(key=lambda c: c.start_time_sec)
    logger.info("[run=%d] extract_chapters: done — %d chapters (deduplicated)", run.id, len(deduped))

    merged = ChapterListSchema(chapters=deduped)
    return {"chapters_result": merged, "chapters_error": None}


async def persist_results_node(state: GraphState) -> dict:
    """Write summaries and chapters to the database and update AnalysisRun status."""
    session: AsyncSession = state["session"]
    run: AnalysisRun = state["run"]
    logger.info("[run=%d] persist_results: saving to DB", run.id)
    run.current_step = "persisting"
    await session.commit()

    summary_result: SummarySchema | None = state.get("summary_result")
    chapters_result: ChapterListSchema | None = state.get("chapters_result")
    summary_error: str | None = state.get("summary_error")
    chapters_error: str | None = state.get("chapters_error")
    pipeline_failed: bool = state.get("pipeline_failed", False)

    if pipeline_failed:
        run.status = AnalysisRunStatus.failed
        run.error_message = "; ".join(state.get("errors", ["Pipeline failed."]))
        run.completed_at = datetime.now(timezone.utc)
        await session.commit()
        return {"final_status": AnalysisRunStatus.failed}

    # Persist summaries
    if summary_result:
        level_map = [
            (SummaryLevel.thesis, summary_result.thesis, None),
            (SummaryLevel.executive, summary_result.executive, None),
            (
                SummaryLevel.detailed,
                "\n".join(summary_result.detailed_outline),
                json.dumps(summary_result.detailed_outline),
            ),
        ]
        for level, text, content_json in level_map:
            summary = Summary(
                run_id=run.id,
                level=level,
                content_text=text,
                content_json=content_json,
            )
            session.add(summary)

    # Persist chapters
    if chapters_result:
        for idx, ch in enumerate(chapters_result.chapters):
            chapter = Chapter(
                run_id=run.id,
                chapter_id=ch.chapter_id,
                title=ch.title,
                start_time_sec=ch.start_time_sec,
                end_time_sec=ch.end_time_sec,
                summary=ch.summary,
                key_points_json=json.dumps(ch.key_points),
                transcript_segment=ch.transcript_segment,
                sort_order=idx,
            )
            session.add(chapter)

    # Determine final status
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
    await session.commit()

    logger.info(
        "[run=%d] persist_results: done — final_status=%s summaries=%s chapters=%s",
        run.id, final_status,
        "ok" if summary_result else f"error({summary_error})",
        "ok" if chapters_result else f"error({chapters_error})",
    )
    return {"final_status": final_status}


def _sec_to_hms(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
