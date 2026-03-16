"""
JSON API routes for VidSense.

All endpoints return JSON. HTMX partial endpoints are handled separately
in pages.py to keep concerns clean.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.db import AnalysisRun, AnalysisRunStatus, Chapter, Summary, Video
from app.models.schemas import (
    AnalyzeRequestSchema,
    AnalysisStatusSchema,
    ChapterResponseSchema,
    RegenerateRequestSchema,
    SummaryResponseSchema,
)
from app.services.processing import start_analysis
from app.services.youtube import get_transcript_for_video, ingest_video

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# POST /api/analyze
# ---------------------------------------------------------------------------


@router.post("/analyze")
async def analyze(
    body: AnalyzeRequestSchema,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """
    Accept a YouTube URL, ingest the transcript (or use cached), create an
    AnalysisRun, then kick off the LLM pipeline in the background.
    Returns immediately with {run_id, video_id}.
    """
    try:
        result = await ingest_video(body.url, session)
    except Exception as exc:
        err_str = str(exc).lower()
        if "rate" in err_str or "429" in err_str or "quota" in err_str:
            raise HTTPException(
                status_code=429,
                detail={
                    "error_code": "RATE_LIMIT",
                    "message": "Processing is temporarily unavailable due to rate limits. Please try again in a moment.",
                    "recoverable": True,
                },
            )
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "UPSTREAM_ERROR",
                "message": "A temporary service error occurred. Please try again.",
                "recoverable": True,
            },
        )

    if not result.success:
        error = result.error
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": error.error_code if error else "UNKNOWN",
                "message": error.message if error else "Ingestion failed.",
                "recoverable": error.recoverable if error else False,
            },
        )

    video = result.video
    transcript_source = result.transcript_source

    # Create the run record so we can return run_id immediately
    from app.models.db import AnalysisRun as Run

    run = Run(
        video_id=video.id,
        focus_prompt=body.focus_prompt,
        status=AnalysisRunStatus.pending,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    run_id = run.id
    video_id = video.id
    quality_warning = result.quality_warning

    # Run pipeline in background
    background_tasks.add_task(
        _run_pipeline_bg,
        run_id=run_id,
        transcript_source_id=transcript_source.id,
    )

    return {
        "run_id": run_id,
        "video_id": video_id,
        "quality_warning": quality_warning,
    }


async def _run_pipeline_bg(
    run_id: int,
    transcript_source_id: int,
) -> None:
    """Background task: runs the pipeline with a fresh DB session."""
    from app.database import AsyncSessionLocal
    from app.models.db import AnalysisRun, TranscriptSource

    try:
        async with AsyncSessionLocal() as session:
            run_result = await session.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
            run = run_result.scalar_one_or_none()
            ts_result = await session.execute(
                select(TranscriptSource).where(TranscriptSource.id == transcript_source_id)
            )
            transcript_source = ts_result.scalar_one_or_none()

            if not run or not transcript_source:
                logger.error(
                    "Background task: run %d or transcript source %d not found",
                    run_id, transcript_source_id,
                )
                return

            await start_analysis(
                run=run,
                transcript_source=transcript_source,
                session=session,
            )
    except Exception as exc:
        logger.exception("Background task for run %d failed unexpectedly: %s", run_id, exc)


# ---------------------------------------------------------------------------
# GET /api/video/{video_id}/status
# ---------------------------------------------------------------------------


@router.get("/video/{video_id}/status", response_model=AnalysisStatusSchema)
async def get_status(
    video_id: int,
    run_id: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Return the current status of the latest (or specified) AnalysisRun for a video.
    """
    if run_id:
        result = await session.execute(
            select(AnalysisRun).where(
                AnalysisRun.id == run_id, AnalysisRun.video_id == video_id
            )
        )
    else:
        result = await session.execute(
            select(AnalysisRun)
            .where(AnalysisRun.video_id == video_id)
            .order_by(AnalysisRun.id.desc())
            .limit(1)
        )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found.")

    summaries_ready = run.status in (AnalysisRunStatus.complete, AnalysisRunStatus.partial)
    chapters_ready = summaries_ready

    # For partial runs, check which components are actually present
    if run.status == AnalysisRunStatus.partial:
        summary_res = await session.execute(
            select(Summary).where(Summary.run_id == run.id).limit(1)
        )
        chapters_res = await session.execute(
            select(Chapter).where(Chapter.run_id == run.id).limit(1)
        )
        summaries_ready = summary_res.scalar_one_or_none() is not None
        chapters_ready = chapters_res.scalar_one_or_none() is not None

    return AnalysisStatusSchema(
        run_id=run.id,
        video_id=run.video_id,
        status=run.status.value,
        summaries_ready=summaries_ready,
        chapters_ready=chapters_ready,
        error_message=run.error_message,
    )


# ---------------------------------------------------------------------------
# GET /api/video/{video_id}/summaries
# ---------------------------------------------------------------------------


@router.get("/video/{video_id}/summaries")
async def get_summaries(
    video_id: int,
    run_id: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    run = await _get_run(video_id, run_id, session)
    result = await session.execute(select(Summary).where(Summary.run_id == run.id))
    summaries = result.scalars().all()

    if not summaries:
        raise HTTPException(status_code=404, detail="Summaries not yet available.")

    response = []
    for s in summaries:
        content_json = None
        if s.content_json:
            try:
                content_json = json.loads(s.content_json)
            except (json.JSONDecodeError, TypeError):
                content_json = None
        response.append(
            SummaryResponseSchema(
                level=s.level.value,
                content_text=s.content_text,
                content_json=content_json,
            )
        )
    return response


# ---------------------------------------------------------------------------
# GET /api/video/{video_id}/chapters
# ---------------------------------------------------------------------------


@router.get("/video/{video_id}/chapters")
async def get_chapters(
    video_id: int,
    run_id: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    run = await _get_run(video_id, run_id, session)
    result = await session.execute(
        select(Chapter)
        .where(Chapter.run_id == run.id)
        .order_by(Chapter.sort_order)
    )
    chapters = result.scalars().all()

    if not chapters:
        raise HTTPException(status_code=404, detail="Chapters not yet available.")

    response = []
    for ch in chapters:
        try:
            key_points = json.loads(ch.key_points_json)
        except (json.JSONDecodeError, TypeError):
            key_points = []
        response.append(
            ChapterResponseSchema(
                chapter_id=ch.chapter_id,
                title=ch.title,
                start_time_sec=ch.start_time_sec,
                end_time_sec=ch.end_time_sec,
                summary=ch.summary,
                key_points=key_points,
                transcript_segment=ch.transcript_segment,
                sort_order=ch.sort_order,
            )
        )
    return response


# ---------------------------------------------------------------------------
# POST /api/video/{video_id}/regenerate
# ---------------------------------------------------------------------------


@router.post("/video/{video_id}/regenerate")
async def regenerate(
    video_id: int,
    body: RegenerateRequestSchema,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """
    Regenerate analysis for a video with an updated focus prompt.
    Reuses the existing TranscriptSource — never re-fetches the transcript.
    """
    # Verify video exists
    video_result = await session.execute(select(Video).where(Video.id == video_id))
    video = video_result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found.")

    # Get cached transcript — must exist, no re-ingestion
    transcript_source = await get_transcript_for_video(video_id, session)
    if not transcript_source:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "NO_CACHED_TRANSCRIPT",
                "message": "No transcript is cached for this video. Please submit the video URL again.",
                "recoverable": False,
            },
        )

    # Create new run with updated focus
    run = AnalysisRun(
        video_id=video_id,
        focus_prompt=body.focus_prompt,
        status=AnalysisRunStatus.pending,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    background_tasks.add_task(
        _run_pipeline_bg,
        run_id=run.id,
        transcript_source_id=transcript_source.id,
    )

    return {"run_id": run.id, "video_id": video_id}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_run(
    video_id: int,
    run_id: int | None,
    session: AsyncSession,
) -> AnalysisRun:
    if run_id:
        result = await session.execute(
            select(AnalysisRun).where(
                AnalysisRun.id == run_id, AnalysisRun.video_id == video_id
            )
        )
    else:
        result = await session.execute(
            select(AnalysisRun)
            .where(AnalysisRun.video_id == video_id)
            .order_by(AnalysisRun.id.desc())
            .limit(1)
        )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found.")
    return run
