"""
Page routes — serve full Jinja2 HTML pages and HTMX partial fragments.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.db import AnalysisRun, AnalysisRunStatus, Chapter, Summary, Video
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
# Video / Read screen
# ---------------------------------------------------------------------------


@router.get("/video/{video_id}", response_class=HTMLResponse)
async def video_page(
    video_id: int,
    run_id: int | None = None,
    qw: int | None = None,  # quality warning flag
    from_cache: int = 0,   # 1 = results were served from a cached run
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
            select(AnalysisRun).where(
                AnalysisRun.id == run_id, AnalysisRun.video_id == video_id
            )
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
            select(AnalysisRun).where(
                AnalysisRun.id == run_id, AnalysisRun.video_id == video_id
            )
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
    summaries_result = await session.execute(
        select(Summary).where(Summary.run_id == run.id)
    )
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
            "has_summaries": bool(summaries),
            "has_chapters": bool(chapters),
            "is_partial": run.status == AnalysisRunStatus.partial,
            "error_message": run.error_message,
            "from_cache": bool(from_cache),
            "processing_time_label": processing_time_label,
        },
    )
