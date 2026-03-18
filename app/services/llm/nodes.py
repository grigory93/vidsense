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
    GlossaryTerm,
    MindMap,
    Summary,
    SummaryLevel,
)
from app.models.schemas import (
    ChapterListSchema,
    GlossaryListSchema,
    MindMapSchema,
    SummarySchema,
)
from app.services.llm.prompts import (
    build_chapter_messages,
    build_chapter_messages_chunk,
    build_glossary_messages,
    build_mind_map_messages,
    build_summary_messages,
    chunk_segments,
    format_transcript_with_timestamps,
)
from app.services.llm.providers import (
    TASK_CHAPTERS,
    TASK_GLOSSARY,
    TASK_MIND_MAP,
    TASK_SUMMARIES,
    get_llm,
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
    """Persist current_step to DB. Non-critical — swallows errors to avoid
    crashing a pipeline node over a progress indicator update."""
    session_factory = state["session_factory"]
    run_id: int = state["run_id"]
    try:
        async with session_factory() as sess:
            result = await sess.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
            db_run = result.scalar_one_or_none()
            if db_run:
                db_run.current_step = step
                await sess.commit()
    except Exception as exc:
        logger.debug("[run=%d] _set_step(%r) failed (non-critical): %s", run_id, step, exc)


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
    llm = get_llm(task=TASK_SUMMARIES)
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
    llm = get_llm(task=TASK_CHAPTERS)
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


async def extract_mind_map_node(state: GraphState) -> dict:
    """Extract a concept mind map from the transcript and persist to DB."""
    if state.get("pipeline_failed"):
        return {}

    run_id: int = state["run_id"]
    session_factory = state["session_factory"]
    llm = get_llm(task=TASK_MIND_MAP)
    transcript_source = state["transcript_source"]
    focus_prompt = state.get("focus_prompt")

    logger.info("[run=%d] extract_mind_map: starting", run_id)
    await _set_step(state, "extracting_mind_map")

    chapter_ids_titles: list[tuple[str, str]] | None = None
    chapters_result = state.get("chapters_result")
    if chapters_result and hasattr(chapters_result, "chapters"):
        chapter_ids_titles = [(c.chapter_id, c.title) for c in chapters_result.chapters]

    messages = build_mind_map_messages(
        transcript_source.raw_text, chapter_ids_titles, focus_prompt
    )

    result, error = await _invoke_with_structured_output(
        llm, MindMapSchema, messages, settings.llm_max_retries
    )

    if result is None:
        logger.error("[run=%d] extract_mind_map: FAILED — %s", run_id, error)
        return {
            "mind_map_result": None,
            "mind_map_error": error or "Mind map extraction failed.",
            "errors": state.get("errors", []) + [f"Mind map extraction failed: {error}"],
        }

    async with session_factory() as sess:
        mm = MindMap(
            run_id=run_id,
            nodes_json=json.dumps([n.model_dump() for n in result.nodes]),
            edges_json=json.dumps([e.model_dump() for e in result.edges]),
        )
        sess.add(mm)
        await sess.commit()

    logger.info(
        "[run=%d] extract_mind_map: done — %d nodes, %d edges",
        run_id, len(result.nodes), len(result.edges),
    )
    return {"mind_map_result": result, "mind_map_error": None}


async def extract_glossary_node(state: GraphState) -> dict:
    """Extract domain-specific glossary terms and map them to transcript timestamps."""
    if state.get("pipeline_failed"):
        return {}

    run_id: int = state["run_id"]
    session_factory = state["session_factory"]
    llm = get_llm(task=TASK_GLOSSARY)
    transcript_source = state["transcript_source"]
    focus_prompt = state.get("focus_prompt")

    logger.info("[run=%d] extract_glossary: starting", run_id)
    await _set_step(state, "extracting_glossary")

    messages = build_glossary_messages(transcript_source.raw_text, focus_prompt)

    result, error = await _invoke_with_structured_output(
        llm, GlossaryListSchema, messages, settings.llm_max_retries
    )

    if result is None:
        logger.error("[run=%d] extract_glossary: FAILED — %s", run_id, error)
        return {
            "glossary_result": None,
            "glossary_error": error or "Glossary extraction failed.",
            "errors": state.get("errors", []) + [f"Glossary extraction failed: {error}"],
        }

    segments: list[dict] = []
    if transcript_source.segments_json:
        try:
            segments = json.loads(transcript_source.segments_json)
        except (json.JSONDecodeError, TypeError):
            segments = []

    async with session_factory() as sess:
        for idx, term_schema in enumerate(result.terms):
            occurrences = _find_term_occurrences(term_schema.term, segments)
            gt = GlossaryTerm(
                run_id=run_id,
                term=term_schema.term,
                definition=term_schema.definition,
                category=term_schema.category,
                related_terms_json=json.dumps(term_schema.related_terms) if term_schema.related_terms else None,
                occurrences_json=json.dumps(occurrences),
                sort_order=idx,
            )
            sess.add(gt)
        await sess.commit()

    logger.info("[run=%d] extract_glossary: done — %d terms", run_id, len(result.terms))
    return {"glossary_result": result, "glossary_error": None}


def _find_term_occurrences(
    term: str, segments: list[dict], max_occurrences: int = 5
) -> list[dict]:
    """Find timestamps where a term appears in the transcript segments.

    Uses a three-tier matching strategy to handle common mismatches:
    1. Exact substring match within a single segment
    2. Sliding-window match across consecutive segments (multi-word terms
       often span YouTube's short caption segments)
    3. Stem-based match — strips common English suffixes so "algorithm"
       matches "algorithms", "optimizing" matches "optimization", etc.
    """
    import re

    if not segments:
        return []

    term_lower = term.lower().strip()
    if not term_lower:
        return []

    occurrences: list[dict] = []
    seen_timestamps: set[int] = set()

    def _add_hit(ts_raw: float | int) -> bool:
        ts = int(ts_raw)
        if ts in seen_timestamps:
            return False
        seen_timestamps.add(ts)
        m, s = divmod(ts, 60)
        h, m = divmod(m, 60)
        display = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        occurrences.append({"timestamp_sec": ts, "display": display})
        return len(occurrences) >= max_occurrences

    # --- Tier 1: exact substring match in a single segment ---
    for seg in segments:
        text = seg.get("text", "").lower()
        if term_lower in text:
            if _add_hit(seg.get("start", 0)):
                return occurrences

    # --- Tier 2: sliding window across consecutive segments ---
    # Multi-word terms like "neural network architecture" may span 2-3 segments.
    if len(term_lower.split()) > 1:
        window_size = min(len(term_lower.split()), 4)
        for i in range(len(segments) - window_size + 1):
            window_text = " ".join(
                segments[i + j].get("text", "") for j in range(window_size)
            ).lower()
            if term_lower in window_text:
                if _add_hit(segments[i].get("start", 0)):
                    return occurrences

    if occurrences:
        occurrences.sort(key=lambda o: o["timestamp_sec"])
        return occurrences

    # --- Tier 3: stem-based matching ---
    # Strip common English suffixes so morphological variants match.
    def _crude_stem(word: str) -> str:
        for suffix in ("ation", "izing", "ised", "ized", "ting", "ning",
                        "sion", "ment", "ness", "ally", "ious", "ical",
                        "ies", "ing", "ion", "ous", "ive", "ble",
                        "ers", "est", "ful", "ity", "ual",
                        "ly", "ed", "er", "al", "es", "ts", "s"):
            if len(word) > len(suffix) + 2 and word.endswith(suffix):
                return word[: -len(suffix)]
        return word

    term_words = [w for w in re.split(r"[\s\-/]+", term_lower) if len(w) > 2]
    if not term_words:
        return occurrences

    term_stems = {_crude_stem(w) for w in term_words}

    for seg in segments:
        seg_words = re.split(r"[\s\-/]+", seg.get("text", "").lower())
        seg_stems = {_crude_stem(w) for w in seg_words if len(w) > 2}
        if term_stems.issubset(seg_stems):
            if _add_hit(seg.get("start", 0)):
                return occurrences

    # Sliding window for stem matching on multi-word terms
    if len(term_words) > 1:
        window_size = min(len(term_words), 4)
        for i in range(len(segments) - window_size + 1):
            combined_words = []
            for j in range(window_size):
                combined_words.extend(
                    re.split(r"[\s\-/]+", segments[i + j].get("text", "").lower())
                )
            combined_stems = {_crude_stem(w) for w in combined_words if len(w) > 2}
            if term_stems.issubset(combined_stems):
                if _add_hit(segments[i].get("start", 0)):
                    return occurrences

    occurrences.sort(key=lambda o: o["timestamp_sec"])
    return occurrences


async def embed_transcript_node(state: GraphState) -> dict:
    """Chunk the transcript and build a FAISS index for Q&A retrieval."""
    if state.get("pipeline_failed"):
        return {}

    run_id: int = state["run_id"]
    video_id: int | None = None
    run_obj = state.get("run")
    if run_obj:
        video_id = run_obj.video_id
    if video_id is None:
        # Resolve from DB so we never save to data/embeddings/None (Q&A looks up by real video_id).
        session_factory = state["session_factory"]
        async with session_factory() as sess:
            result = await sess.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
            run_from_db = result.scalar_one_or_none()
            if run_from_db is not None:
                video_id = run_from_db.video_id
    if video_id is None:
        return {"embedding_error": "Could not resolve video_id for this run."}

    logger.info("[run=%d] embed_transcript: starting", run_id)
    await _set_step(state, "embedding_transcript")

    transcript_source = state["transcript_source"]
    segments: list[dict] = []
    if transcript_source.segments_json:
        try:
            segments = json.loads(transcript_source.segments_json)
        except (json.JSONDecodeError, TypeError):
            segments = []

    if not segments and not transcript_source.raw_text.strip():
        return {"embedding_error": "No transcript available for embedding."}

    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        from langchain_community.vectorstores import FAISS

        from app.services.llm.providers import get_embedding_model

        embedding_model = get_embedding_model()

        if segments:
            texts = []
            metadatas = []
            for seg in segments:
                text = seg.get("text", "").strip()
                if text:
                    ts = int(seg.get("start", 0))
                    dur = float(seg.get("duration", 0))
                    texts.append(text)
                    metadatas.append({"start_time_sec": ts, "duration": dur})

            splitter = RecursiveCharacterTextSplitter(
                chunk_size=1000, chunk_overlap=200, separators=["\n\n", "\n", ". ", " "]
            )

            merged_docs = []
            merged_metas = []
            current_text = ""
            current_start = 0
            for text, meta in zip(texts, metadatas):
                if len(current_text) + len(text) > 800:
                    if current_text.strip():
                        merged_docs.append(current_text.strip())
                        merged_metas.append({"start_time_sec": current_start})
                    current_text = text
                    current_start = meta["start_time_sec"]
                else:
                    if not current_text:
                        current_start = meta["start_time_sec"]
                    current_text += " " + text
            if current_text.strip():
                merged_docs.append(current_text.strip())
                merged_metas.append({"start_time_sec": current_start})

            final_texts = []
            final_metas = []
            for doc, meta in zip(merged_docs, merged_metas):
                splits = splitter.split_text(doc)
                for split in splits:
                    final_texts.append(split)
                    final_metas.append(meta)
        else:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=1000, chunk_overlap=200
            )
            splits = splitter.split_text(transcript_source.raw_text)
            final_texts = splits
            final_metas = [{"start_time_sec": 0}] * len(splits)

        store = FAISS.from_texts(final_texts, embedding_model, metadatas=final_metas)

        import os
        from app.config import settings as app_settings
        os.makedirs(app_settings.embeddings_dir, exist_ok=True)
        save_path = os.path.join(app_settings.embeddings_dir, str(video_id))
        store.save_local(save_path)

        logger.info(
            "[run=%d] embed_transcript: done — %d chunks, saved to %s",
            run_id, len(final_texts), save_path,
        )
        return {"embedding_error": None}

    except Exception as exc:
        logger.error("[run=%d] embed_transcript: FAILED — %s", run_id, exc)
        return {
            "embedding_error": str(exc),
            "errors": state.get("errors", []) + [f"Embedding failed: {exc}"],
        }


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

        # V2 feature errors are logged but don't downgrade core status
        mind_map_error = state.get("mind_map_error")
        glossary_error = state.get("glossary_error")
        embedding_error = state.get("embedding_error")
        v2_warnings = []
        if mind_map_error:
            v2_warnings.append(f"Mind map: {mind_map_error}")
        if glossary_error:
            v2_warnings.append(f"Glossary: {glossary_error}")
        if embedding_error:
            v2_warnings.append(f"Embeddings: {embedding_error}")
        if v2_warnings:
            existing = run.error_message or ""
            v2_msg = "; ".join(v2_warnings)
            run.error_message = f"{existing}; {v2_msg}".strip("; ") if existing else v2_msg

        run.status = final_status
        run.current_step = None
        run.completed_at = datetime.now(timezone.utc)
        await sess.commit()

    logger.info(
        "[run=%d] finalize_run: done — final_status=%s summaries=%s chapters=%s mind_map=%s glossary=%s embeddings=%s",
        run_id, final_status,
        "ok" if summary_result else f"error({summary_error})",
        "ok" if chapters_result else f"error({chapters_error})",
        "ok" if state.get("mind_map_result") else f"error({state.get('mind_map_error')})",
        "ok" if state.get("glossary_result") else f"error({state.get('glossary_error')})",
        "ok" if not state.get("embedding_error") else f"error({state.get('embedding_error')})",
    )
    return {"final_status": final_status}


def _sec_to_hms(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
