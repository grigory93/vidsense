"""
LangGraph state type definition for the VidSense pipeline.

LangGraph calls get_type_hints() on the state schema at compile time,
so all type annotations must be resolvable at runtime. We use Any for
external types that would create circular imports if imported directly.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any

from typing_extensions import TypedDict


class GraphState(TypedDict, total=False):
    # Inputs (typed as Any to avoid runtime annotation resolution issues with LangGraph)
    session_factory: Any  # async_sessionmaker[AsyncSession] — each node creates its own session
    run_id: Any           # int — stable ID used to reload run in fresh sessions
    run: Any              # AnalysisRun (attached to the caller's session; nodes use run_id instead)
    transcript_source: Any  # TranscriptSource
    focus_prompt: Any  # str | None
    language_code: Any  # str — normalized ISO 639-1 code of the transcript
    video_tags: Any       # list[str] | None — creator tags from YouTube API
    video_comments: Any   # list[dict] | None — top comments from YouTube API
    video_category: Any   # str | None — resolved category name

    # Intermediate results — summaries & chapters (V1)
    summary_result: Any    # SummarySchema | None
    summary_error: Any     # str | None
    chapters_result: Any   # ChapterListSchema | None
    chapters_error: Any    # str | None

    # Intermediate results — V2 features
    mind_map_result: Any   # MindMapSchema | None
    mind_map_error: Any    # str | None
    glossary_result: Any   # GlossaryListSchema | None
    glossary_error: Any    # str | None
    embedding_error: Any   # str | None

    # Control flow
    pipeline_failed: bool
    errors: Annotated[list, operator.add]

    # Output
    final_status: Any
