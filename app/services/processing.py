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

from sqlalchemy.ext.asyncio import AsyncSession

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
    logger.info(
        "[run=%d] pipeline starting — video_id=%d focus=%r llm=%s",
        run.id, run.video_id, run.focus_prompt, type(llm).__name__,
    )

    try:
        await run_pipeline(
            llm=llm,
            session=session,
            run=run,
            transcript_source=transcript_source,
            focus_prompt=run.focus_prompt,
        )
    except Exception as exc:
        logger.exception("[run=%d] Unhandled pipeline error: %s", run.id, exc)
        run.status = AnalysisRunStatus.failed
        run.current_step = None
        run.error_message = f"Unexpected error: {exc}"
        run.completed_at = datetime.now(timezone.utc)
        await session.commit()

    await session.refresh(run)
    logger.info("[run=%d] pipeline finished — status=%s", run.id, run.status)
    return run
