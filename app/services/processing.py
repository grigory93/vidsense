"""
Top-level processing orchestration.

Called by API routes to:
1. Mark an existing AnalysisRun as processing
2. Invoke the LangGraph pipeline
3. Handle top-level errors and mark run as failed if needed
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.db import AnalysisRun, AnalysisRunStatus, TranscriptSource
from app.services.llm.graph import run_pipeline
from app.services.llm.providers import get_llm

logger = logging.getLogger(__name__)


async def start_analysis(
    run: AnalysisRun,
    transcript_source: TranscriptSource,
    session: AsyncSession,
) -> AnalysisRun:
    """
    Mark an existing pending AnalysisRun as processing and run the pipeline.
    The run must already exist in the DB (created by the API handler).
    """
    run.status = AnalysisRunStatus.processing
    await session.commit()

    llm = get_llm()
    run_id = run.id
    logger.info(
        "[run=%d] pipeline starting — video_id=%d focus=%r llm=%s",
        run_id, run.video_id, run.focus_prompt, type(llm).__name__,
    )

    try:
        await run_pipeline(
            llm=llm,
            session_factory=AsyncSessionLocal,
            run=run,
            transcript_source=transcript_source,
            focus_prompt=run.focus_prompt,
        )
    except Exception as exc:
        logger.exception("[run=%d] Unhandled pipeline error: %s", run_id, exc)
        # Use a fresh session — the original may be in an invalid state
        async with AsyncSessionLocal() as recovery_sess:
            try:
                result = await recovery_sess.execute(
                    select(AnalysisRun).where(AnalysisRun.id == run_id)
                )
                db_run = result.scalar_one_or_none()
                if db_run:
                    db_run.status = AnalysisRunStatus.failed
                    db_run.current_step = None
                    db_run.error_message = f"Unexpected error: {exc}"
                    db_run.completed_at = datetime.now(timezone.utc)
                    await recovery_sess.commit()
            except Exception as inner_exc:
                logger.error("[run=%d] Failed to mark run as failed: %s", run_id, inner_exc)

    # Reload run state from a fresh session to return accurate status
    async with AsyncSessionLocal() as read_sess:
        result = await read_sess.execute(
            select(AnalysisRun).where(AnalysisRun.id == run_id)
        )
        refreshed = result.scalar_one_or_none()

    if refreshed:
        logger.info("[run=%d] pipeline finished — status=%s", run_id, refreshed.status)
        return refreshed

    logger.info("[run=%d] pipeline finished", run_id)
    return run
