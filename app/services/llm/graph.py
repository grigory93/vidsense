"""
LangGraph StateGraph definition for VidSense processing pipeline.

Graph topology:
  START → validate_input → [gen_summaries, extract_chapters] (parallel fan-out)
        → persist_results → END
"""
from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app.models.db import AnalysisRun, TranscriptSource
from app.services.llm.nodes import (
    extract_chapters_node,
    finalize_run_node,
    gen_summaries_node,
    validate_input_node,
)
from app.services.llm.state import GraphState

logger = logging.getLogger(__name__)


def _build_graph() -> StateGraph:
    graph = StateGraph(GraphState)

    graph.add_node("validate_input", validate_input_node)
    graph.add_node("gen_summaries", gen_summaries_node)
    graph.add_node("extract_chapters", extract_chapters_node)
    graph.add_node("finalize_run", finalize_run_node)

    graph.add_edge(START, "validate_input")

    # Fan-out: both summaries and chapters run after validation
    graph.add_edge("validate_input", "gen_summaries")
    graph.add_edge("validate_input", "extract_chapters")

    # Both fan-in to finalize
    graph.add_edge("gen_summaries", "finalize_run")
    graph.add_edge("extract_chapters", "finalize_run")

    graph.add_edge("finalize_run", END)

    return graph


_compiled_graph = _build_graph().compile()


async def run_pipeline(
    llm: BaseChatModel,
    session_factory,
    run: AnalysisRun,
    transcript_source: TranscriptSource,
    focus_prompt: str | None = None,
) -> GraphState:
    """
    Execute the full VidSense processing pipeline.
    Returns the final GraphState after all nodes complete.

    session_factory must be an async_sessionmaker — each parallel node opens its own
    independent session to avoid concurrent-commit errors on a shared session.
    """
    initial_state: GraphState = {
        "llm": llm,
        "session_factory": session_factory,
        "run_id": run.id,
        "run": run,
        "transcript_source": transcript_source,
        "focus_prompt": focus_prompt,
        "errors": [],
        "pipeline_failed": False,
        "summary_result": None,
        "summary_error": None,
        "chapters_result": None,
        "chapters_error": None,
    }

    try:
        final_state = await _compiled_graph.ainvoke(initial_state)
        return final_state  # type: ignore[return-value]
    except Exception as exc:
        logger.exception("Pipeline raised an unexpected error: %s", exc)
        raise
