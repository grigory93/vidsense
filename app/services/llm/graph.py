"""
LangGraph StateGraph definition for VidSense processing pipeline.

Graph topology:
  START → validate_input → gen_summaries                          → finalize_run → END
                         → extract_chapters → extract_mind_map   → finalize_run
                         → extract_glossary                       → finalize_run
                         → embed_transcript                       → finalize_run

  extract_mind_map is sequenced after extract_chapters so that chapters_result
  is available in state for chapter cross-reference enrichment in the prompt.

Each parallel node constructs its own LLM via get_llm(task=...) so
different tasks can use different models without sharing state.
"""
from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from app.models.db import AnalysisRun, TranscriptSource
from app.services.llm.nodes import (
    embed_transcript_node,
    extract_chapters_node,
    extract_glossary_node,
    extract_mind_map_node,
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
    graph.add_node("extract_mind_map", extract_mind_map_node)
    graph.add_node("extract_glossary", extract_glossary_node)
    graph.add_node("embed_transcript", embed_transcript_node)
    graph.add_node("finalize_run", finalize_run_node)

    graph.add_edge(START, "validate_input")

    # Fan-out: summaries, glossary, and embedding run fully in parallel after validation.
    # extract_mind_map depends on extract_chapters so that chapters_result is in state
    # when the mind map node reads it for chapter cross-reference enrichment.
    graph.add_edge("validate_input", "gen_summaries")
    graph.add_edge("validate_input", "extract_chapters")
    graph.add_edge("validate_input", "extract_glossary")
    graph.add_edge("validate_input", "embed_transcript")

    graph.add_edge("extract_chapters", "extract_mind_map")

    # All fan-in to finalize.
    # extract_chapters does NOT have a direct edge here — it routes through
    # extract_mind_map so that chapters_result is populated in state before
    # the mind map node reads it for chapter cross-reference enrichment.
    graph.add_edge("gen_summaries", "finalize_run")
    graph.add_edge("extract_mind_map", "finalize_run")
    graph.add_edge("extract_glossary", "finalize_run")
    graph.add_edge("embed_transcript", "finalize_run")

    graph.add_edge("finalize_run", END)

    return graph


_compiled_graph = _build_graph().compile()


async def run_pipeline(
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

    Each node constructs its own LLM via get_llm(task=...) so per-task model
    overrides are respected without passing a shared LLM through state.
    """
    initial_state: GraphState = {
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
        "mind_map_result": None,
        "mind_map_error": None,
        "glossary_result": None,
        "glossary_error": None,
        "embedding_error": None,
    }

    try:
        final_state = await _compiled_graph.ainvoke(initial_state)
        return final_state  # type: ignore[return-value]
    except Exception as exc:
        logger.exception("Pipeline raised an unexpected error: %s", exc)
        raise
