# VidSense Read Module PRD Handoff Summary

## Purpose

This summary explains how `docs/VIDSENSE_APP_PRD.md` was revised so a Planner can use the PRD as the source of truth for creating a detailed implementation plan for the Version 1 MVP.

## What Changed

* The PRD now clearly distinguishes the broader VidSense product vision from the `Read` module's `V1 MVP` scope.
* The MVP is explicitly narrowed to one core outcome:
  * public YouTube URL
  * available transcript/caption source
  * layered summaries
  * smart chapters
  * clickable playable timestamps
  * optional global focus prompt
  * regenerate without transcript re-ingestion during the active workflow
* Post-MVP features were separated from V1 and retained only as future roadmap items:
  * Mind Maps
  * Contextual Glossary
  * Semantic Q&A
  * Action Item Extraction
* Product-facing requirements were preserved while implementation-specific technology choices were removed from the PRD.

## Key PRD Decisions Now Locked In

* `V1 input source`: public YouTube videos only.
* `V1 transcript policy`: V1 requires an available YouTube caption or transcript source.
* `V1 auto-transcription`: out of scope.
* `V1 language support`: English only.
* `V1 video length support`: up to 90 minutes.
* `V1 focus behavior`: one optional global focus prompt applies across summaries and chapters.
* `V1 regeneration behavior`: regenerating with a new focus prompt must reuse the same source context and must not re-ingest the transcript during the active workflow.

## Canonical MVP Outputs

* Transcript-backed reading output derived from the available transcript source.
* Layered summaries with at least three depths:
  * short thesis / 1-minute summary
  * medium executive summary
  * detailed outline
* Smart chapters with a canonical structure:
  * `chapter_id`
  * `title`
  * `start_time_sec`
  * `end_time_sec`
  * `summary`
  * `key_points`
  * `transcript_segment`
* A single `Read` screen with one embedded or sticky video player and clickable timestamps.

## Important Consistency Fixes Applied

* Replaced the ambiguous promise to "retrieve or generate" transcripts with a stricter V1 policy: retrieve an available YouTube transcript/caption source.
* Clarified that chapter-level transcript segments are required MVP output, while full transcript display is optional.
* Aligned latency expectations across the full supported range:
  * up to 60 minutes: initial readable result within 2 minutes, full processing within 5 minutes
  * 60 to 90 minutes: initial readable result within 4 minutes, full processing within 10 minutes
* Strengthened regeneration language so it is a product requirement, not a best-effort optimization.
* Added built-in auto-transcription explicitly to `Out Of Scope For V1`.

## Product Validation Expectations

The planner should treat the following as release-critical validation themes:

* timestamp seeking accuracy
* chapter coherence and full-video coverage
* summary distinctness and faithfulness to source
* stable regeneration behavior without transcript re-ingestion
* clear and recoverable failure states

## Failure States The Plan Must Cover

* no transcript available
* poor transcript quality
* non-supported language
* video exceeds supported length
* malformed or low-quality focus prompt
* temporary upstream/rate-limit failure
* partial extraction failure where some outputs succeed and others fail

## Non-Functional Requirements The Plan Must Respect

* time-to-first-result and full processing targets by video length band
* visible processing state for longer jobs
* retries for transient failures
* preservation of processed source context during the active workflow
* cost-aware regeneration behavior
* graceful degradation when only part of the pipeline succeeds

## Planner Guidance

Use `docs/VIDSENSE_APP_PRD.md` as the authoritative product requirements document.

When creating the implementation plan, break work into at least these streams:

* ingestion and transcript retrieval
* processing pipeline orchestration
* summary generation
* chapter generation and timestamp binding
* regenerate flow using existing source context
* read-screen UX and player interaction
* failure-state UX and messaging
* validation, QA, and success-metric instrumentation

The implementation plan should preserve the V1 discipline of shipping the reading workflow first and should not pull future-version features back into MVP scope.
