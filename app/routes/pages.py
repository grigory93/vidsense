"""
Page routes — serve full Jinja2 HTML pages and HTMX partial fragments.
"""

from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.db import (
    AnalysisRun,
    AnalysisRunStatus,
    Chapter,
    GlossaryTerm,
    MindMap,
    Summary,
    Video,
)
from app.models.schemas import _seconds_to_mmss

logger = logging.getLogger(__name__)
router = APIRouter()


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    templates = get_templates(request)
    return templates.TemplateResponse(request, "index.html")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    templates = get_templates(request)
    return templates.TemplateResponse(request, "settings.html")


# ---------------------------------------------------------------------------
# Video / Read screen
# ---------------------------------------------------------------------------


@router.get("/video/{video_id}", response_class=HTMLResponse)
async def video_page(
    video_id: int,
    run_id: int | None = None,
    qw: int | None = None,  # quality warning flag
    from_cache: int = 0,  # 1 = results were served from a cached run
    request: Request = None,
    session: AsyncSession = Depends(get_session),
):
    templates = get_templates(request)

    video_result = await session.execute(select(Video).where(Video.id == video_id))
    video = video_result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")

    # Get the relevant run
    if run_id:
        run_result = await session.execute(
            select(AnalysisRun).where(AnalysisRun.id == run_id, AnalysisRun.video_id == video_id)
        )
    else:
        run_result = await session.execute(
            select(AnalysisRun)
            .where(AnalysisRun.video_id == video_id)
            .order_by(AnalysisRun.id.desc())
            .limit(1)
        )
    run = run_result.scalar_one_or_none()

    return templates.TemplateResponse(
        request,
        "video.html",
        {
            "video": video,
            "run": run,
            "quality_warning": bool(qw),
            "initial_focus_prompt": run.focus_prompt if run else None,
            "from_cache": bool(from_cache),
        },
    )


# ---------------------------------------------------------------------------
# HTMX partials
# ---------------------------------------------------------------------------


@router.get("/partials/video/{video_id}/status", response_class=HTMLResponse)
async def partial_status(
    video_id: int,
    run_id: int | None = None,
    from_cache: int = 0,
    request: Request = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Polled by HTMX every 3s. Returns the processing spinner or, when complete,
    returns the full results partial.
    """
    templates = get_templates(request)

    if run_id:
        run_result = await session.execute(
            select(AnalysisRun).where(AnalysisRun.id == run_id, AnalysisRun.video_id == video_id)
        )
    else:
        run_result = await session.execute(
            select(AnalysisRun)
            .where(AnalysisRun.video_id == video_id)
            .order_by(AnalysisRun.id.desc())
            .limit(1)
        )
    run = run_result.scalar_one_or_none()

    # Load video for templates that need duration / metadata
    video_result = await session.execute(select(Video).where(Video.id == video_id))
    video = video_result.scalar_one_or_none()

    if not run:
        return templates.TemplateResponse(
            request,
            "partials/error.html",
            {"error_code": "NOT_FOUND", "message": "Analysis run not found."},
        )

    if run.status in (AnalysisRunStatus.pending, AnalysisRunStatus.processing):
        # Check for any intermediate results already persisted by the pipeline
        interim_summaries_result = await session.execute(
            select(Summary).where(Summary.run_id == run.id)
        )
        interim_summaries = interim_summaries_result.scalars().all()

        interim_chapters_result = await session.execute(
            select(Chapter).where(Chapter.run_id == run.id).order_by(Chapter.sort_order)
        )
        interim_chapters = interim_chapters_result.scalars().all()

        interim_enriched_summaries: dict = {}
        for s in interim_summaries:
            content_json = None
            if s.content_json:
                try:
                    content_json = json.loads(s.content_json)
                except (json.JSONDecodeError, TypeError):
                    content_json = None
            interim_enriched_summaries[s.level.value] = {
                "content_text": s.content_text,
                "content_json": content_json,
            }

        interim_enriched_chapters = []
        for ch in interim_chapters:
            try:
                key_points = json.loads(ch.key_points_json)
            except (json.JSONDecodeError, TypeError):
                key_points = []
            interim_enriched_chapters.append(
                {
                    "id": ch.id,
                    "chapter_id": ch.chapter_id,
                    "title": ch.title,
                    "start_time_sec": ch.start_time_sec,
                    "end_time_sec": ch.end_time_sec,
                    "start_display": _seconds_to_mmss(ch.start_time_sec),
                    "end_display": _seconds_to_mmss(ch.end_time_sec),
                    "summary": ch.summary,
                    "key_points": key_points,
                    "transcript_segment": ch.transcript_segment,
                    "sort_order": ch.sort_order,
                }
            )

        return templates.TemplateResponse(
            request,
            "partials/processing.html",
            {
                "run": run,
                "video_id": video_id,
                "video": video,
                "interim_summaries": interim_enriched_summaries,
                "interim_chapters": interim_enriched_chapters,
                "has_interim_summaries": bool(interim_summaries),
                "has_interim_chapters": bool(interim_chapters),
            },
        )

    if run.status == AnalysisRunStatus.failed:
        return templates.TemplateResponse(
            request,
            "partials/error.html",
            {
                "error_code": "PIPELINE_FAILED",
                "message": run.error_message or "Processing failed. Please try again.",
                "recoverable": True,
                "video_id": video_id,
            },
        )

    # complete or partial — load actual data
    summaries_result = await session.execute(select(Summary).where(Summary.run_id == run.id))
    summaries = summaries_result.scalars().all()

    chapters_result = await session.execute(
        select(Chapter).where(Chapter.run_id == run.id).order_by(Chapter.sort_order)
    )
    chapters = chapters_result.scalars().all()

    # Enrich chapters with display timestamps and parsed key_points
    enriched_chapters = []
    for ch in chapters:
        try:
            key_points = json.loads(ch.key_points_json)
        except (json.JSONDecodeError, TypeError):
            key_points = []
        enriched_chapters.append(
            {
                "id": ch.id,
                "chapter_id": ch.chapter_id,
                "title": ch.title,
                "start_time_sec": ch.start_time_sec,
                "end_time_sec": ch.end_time_sec,
                "start_display": _seconds_to_mmss(ch.start_time_sec),
                "end_display": _seconds_to_mmss(ch.end_time_sec),
                "summary": ch.summary,
                "key_points": key_points,
                "transcript_segment": ch.transcript_segment,
                "sort_order": ch.sort_order,
            }
        )

    # Enrich summaries with parsed detailed outline
    enriched_summaries: dict = {}
    for s in summaries:
        content_json = None
        if s.content_json:
            try:
                content_json = json.loads(s.content_json)
            except (json.JSONDecodeError, TypeError):
                content_json = None
        enriched_summaries[s.level.value] = {
            "content_text": s.content_text,
            "content_json": content_json,
        }

    # Build detailed_outline_groups for the composite Detailed Outline + Chapter Explorer tab.
    # Each group maps one chapter to a proportional slice of the detailed outline points.
    detailed_points: list[str] = []
    detailed_entry = enriched_summaries.get("detailed", {})
    if detailed_entry.get("content_json"):
        detailed_points = detailed_entry["content_json"]
    elif detailed_entry.get("content_text"):
        detailed_points = [
            line.lstrip("•-*0123456789. ").strip()
            for line in detailed_entry["content_text"].split("\n")
            if line.strip()
        ]

    detailed_outline_groups: list[dict] = []
    if enriched_chapters:
        # Always create one group per chapter. Outline points are distributed
        # proportionally; if no outline exists, the points list is empty but
        # the chapter header/summary/key-points/transcript still render.
        n_points = len(detailed_points)
        n_chapters = len(enriched_chapters)
        for i, chapter in enumerate(enriched_chapters):
            enriched_pts: list[dict] = []
            if detailed_points:
                start_idx = round(i * n_points / n_chapters)
                end_idx = round((i + 1) * n_points / n_chapters)
                chapter_points = detailed_points[start_idx:end_idx]
                n_ch = len(chapter_points)
                ch_dur = chapter["end_time_sec"] - chapter["start_time_sec"]
                for j, text in enumerate(chapter_points):
                    # Distribute timestamps proportionally within the chapter.
                    # Use j/n_ch so the last point doesn't land on the chapter
                    # boundary (which is the next chapter's start).
                    ts = chapter["start_time_sec"] + round(j * ch_dur / max(n_ch, 1))
                    ts = max(chapter["start_time_sec"], min(ts, chapter["end_time_sec"]))
                    raw_end = chapter["start_time_sec"] + round((j + 1) * ch_dur / max(n_ch, 1))
                    raw_end = min(raw_end, chapter["end_time_sec"])
                    # Clamp end_ts to chapter end *after* max(ts+1, ...). Doing min(end, chapter_end)
                    # before max(ts+1, ...) makes end_ts = chapter_end+1 when ts was clamped to
                    # chapter_end (player.js uses start <= t < end; overflow highlights next chapter).
                    end_ts = min(chapter["end_time_sec"], max(ts + 1, raw_end))
                    enriched_pts.append(
                        {
                            "text": text,
                            "timestamp_sec": ts,
                            "end_timestamp_sec": end_ts,
                            "timestamp_display": _seconds_to_mmss(ts),
                        }
                    )
            detailed_outline_groups.append({"chapter": chapter, "points": enriched_pts})
    elif detailed_points:
        # Outline available but no chapters — single ungrouped block (no timestamps)
        detailed_outline_groups = [{"chapter": None, "points": detailed_points}]

    # Query V2 artifacts: mind map, glossary, embeddings availability
    mind_map_row = (
        await session.execute(select(MindMap).where(MindMap.run_id == run.id))
    ).scalar_one_or_none()
    mind_map_data: dict | None = None
    if mind_map_row:
        try:
            mind_map_data = {
                "nodes": json.loads(mind_map_row.nodes_json),
                "edges": json.loads(mind_map_row.edges_json),
            }
        except (json.JSONDecodeError, TypeError):
            mind_map_data = None

    glossary_rows = (
        (
            await session.execute(
                select(GlossaryTerm)
                .where(GlossaryTerm.run_id == run.id)
                .order_by(GlossaryTerm.sort_order)
            )
        )
        .scalars()
        .all()
    )
    glossary_terms_data: list[dict] = []
    for gt in glossary_rows:
        occurrences = []
        try:
            occurrences = json.loads(gt.occurrences_json)
        except (json.JSONDecodeError, TypeError):
            pass
        related = []
        if gt.related_terms_json:
            try:
                related = json.loads(gt.related_terms_json)
            except (json.JSONDecodeError, TypeError):
                pass
        glossary_terms_data.append(
            {
                "term": gt.term,
                "definition": gt.definition,
                "category": gt.category,
                "related_terms": related,
                "occurrences": occurrences,
            }
        )

    from app.config import settings as app_settings

    embeddings_path = os.path.join(app_settings.embeddings_dir, str(video_id))
    has_embeddings = os.path.isdir(embeddings_path)

    # Compute total processing time
    processing_time_label: str | None = None
    if run.completed_at and run.created_at:
        delta_sec = int((run.completed_at - run.created_at).total_seconds())
        if delta_sec >= 60:
            m, s = divmod(delta_sec, 60)
            processing_time_label = f"{m}m {s}s"
        else:
            processing_time_label = f"{delta_sec}s"

    return templates.TemplateResponse(
        request,
        "partials/results.html",
        {
            "run": run,
            "video": video,
            "video_id": video_id,
            "summaries": enriched_summaries,
            "chapters": enriched_chapters,
            "detailed_outline_groups": detailed_outline_groups,
            "has_summaries": bool(summaries),
            "has_chapters": bool(chapters),
            "mind_map": mind_map_data,
            "glossary_terms": glossary_terms_data,
            "has_embeddings": has_embeddings,
            "is_partial": run.status == AnalysisRunStatus.partial,
            "error_message": run.error_message,
            "from_cache": bool(from_cache),
            "processing_time_label": processing_time_label,
        },
    )
