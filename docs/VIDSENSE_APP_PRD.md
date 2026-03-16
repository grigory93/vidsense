### Product Requirements Document (PRD): VidSense "Read" Module

#### 0. Purpose

This document defines the product requirements for the VidSense "Read" module, with a clear focus on Version 1 MVP while preserving the broader product direction for later versions. The V1 goal is to turn a YouTube video into a readable learning experience built around transcript-based understanding, layered summaries, smart chapters, and playable timestamps.

#### 1. Product Vision

VidSense is an AI-powered knowledge extraction product that helps users transform long-form YouTube videos into concise, structured, and useful learning assets. It is intended for students, researchers, professionals, and self-directed learners who want to understand video content faster without losing important meaning or context.

#### 2. Versioning And Prioritization

* **MVP / V1:** YouTube URL ingestion, transcript retrieval, layered summaries, smart chapters, playable timestamps, optional global focus prompt, and regeneration using the existing processed source when available.
* **V1.1:** Improvements to quality, accuracy, speed, and resilience; broader support for edge cases and clearer confidence/error messaging.
* **Later:** Mind Maps, Contextual Glossary, Semantic Q&A, Action Item Extraction, and other advanced reading or visualization experiences.

#### 3. MVP Scope

Version 1 MVP is focused on a single core outcome: a user provides a YouTube video URL, the system retrieves an available YouTube transcript or caption source, and the product returns a readable output composed of layered summaries and smart chapters with clickable timestamps that play the video from the correct moment. V1 includes one optional global focus field that influences the generated output, and it supports regenerating results for the same source without forcing the user to start over or re-ingest the transcript source. V1 does not include mind maps, glossary views, chat/Q&A, action-only extraction, advanced per-output prompt targeting, complex visualization workflows, or built-in auto-transcription.

#### 4. Primary User Flow

1. User pastes a YouTube URL into the "Read" workflow.
2. User optionally adds a short focus prompt describing what they want emphasized.
3. User starts processing.
4. System validates the URL, retrieves the transcript or caption source, and begins analysis.
5. User receives a "Read" result page with:
   * layered summary options
   * smart chapters
   * a single embedded or sticky video player
   * clickable timestamps that seek the video
6. User reads the summaries and chapters, and can jump from text to video using timestamps.
7. User can update the focus field and regenerate output for the same video.

#### 5. Inputs, Outputs, And Assumptions

##### Supported Inputs

* **MVP:** Public YouTube video URL.
* **Optional Input:** One global focus field describing what the user wants emphasized in the output.

##### Expected Outputs

* Transcript-backed reading output derived from the available transcript source, including chapter-level transcript segments.
* Full transcript display may be included when available, but chapter-level transcript segments are the required MVP transcript view.
* Layered summaries at multiple levels of detail.
* Smart chapters with summaries and playable timestamps.

##### Source Assumptions And Constraints

* V1 supports public YouTube videos only.
* V1 requires an available YouTube caption or transcript source.
* Built-in auto-transcription is out of scope for V1.
* V1 supports English-language videos only.
* V1 supports videos up to 90 minutes in length.
* If no transcript or caption source is available, the user must receive a clear failure state and recommended next step.

#### 6. Main V1 Experience

The "Read" experience in V1 is a text-first view of a YouTube video's content. It should help users understand a long video quickly, navigate to the right section, and revisit the source material at the exact relevant moment. The experience should prioritize clarity, conciseness, correctness, and practical usefulness over feature breadth.

#### 7. Feature Requirements

##### Feature 1 [MVP]: Layered Summaries

* **Description:** Users receive multiple summary depths so they can choose between a fast overview and a more complete understanding.
* **Functional Requirements:**
* Provide at least three summary levels:
  * a short thesis or "1-minute" summary
  * a medium-length executive summary
  * a detailed outline or structured breakdown
* Summary content must be grounded in the transcript source.
* Summary content should reflect the user's optional focus prompt when provided.
* Summary content should be easy to scan and written for clarity and conciseness.

* **Acceptance Criteria:**
* A processed video returns all defined summary levels in one result view.
* Each summary level is meaningfully distinct in depth, not merely a reworded duplicate.
* Summary points must not introduce unsupported claims that are not grounded in the source transcript.
* For English-language videos up to 60 minutes long, the initial readable result should appear within 2 minutes and full summary generation should complete within 5 minutes under normal operating conditions.
* For English-language videos between 60 and 90 minutes long, the initial readable result should appear within 4 minutes and full summary generation should complete within 10 minutes under normal operating conditions.
* If a focus prompt is provided, the output must visibly reflect that focus without discarding the core meaning of the source.

##### Feature 2 [MVP]: Smart Chapters

* **Description:** The system breaks the video into clear, useful chapters that help the user browse by topic and jump directly to the relevant segment.
* **Functional Requirements:**
* Chapters must be presented in chronological order.
* Each chapter must use one canonical data structure:
  * `chapter_id`: unique identifier
  * `title`: concise chapter heading
  * `start_time_sec`: integer start timestamp in seconds
  * `end_time_sec`: integer end timestamp in seconds
  * `summary`: short chapter summary
  * `key_points`: array of key points
  * `transcript_segment`: transcript text for that chapter
* The UI may derive display timestamps such as `04:12` from the raw time fields.
* Chapters should cover the full supported video content without major unexplained gaps.
* The transcript segment should be collapsed by default and expandable on demand.

* **Acceptance Criteria:**
* Clicking a chapter timestamp seeks the video player to the correct chapter start.
* `start_time_sec` must always be less than `end_time_sec`.
* Chapters must be coherent enough that a user can understand the topic transition from one card to the next.
* For supported videos, the chapter list should cover the video from beginning to end with minimal overlap or omission.
* If chapter generation fails, the user must receive a clear error or partial-result state rather than a silent failure.

##### Feature 3 [MVP]: Optional Focus Prompt

* **Description:** Users may provide one optional global focus field to influence the summaries and chapters toward a specific topic, question, or learning goal.
* **Functional Requirements:**
* Provide one optional text input before analysis starts.
* The focus input applies globally to the generated summaries and chapters.
* Users can regenerate the output for the same video using an updated focus prompt.
* The product should not require the user to re-enter the video URL to regenerate focused output.

* **Acceptance Criteria:**
* A user can submit a supported video without a focus prompt and still receive complete default output.
* A user can submit a focus prompt and receive output that reflects the requested emphasis.
* Regeneration with a new focus prompt must reuse the existing source video context and must not require transcript re-ingestion for the same video.
* Malformed, ambiguous, or low-quality focus prompts must not break the user flow; the system should either continue safely or return clear guidance.

#### 8. UI/UX Requirements For MVP

* Present one primary "Read" screen for the processed video.
* Show a single embedded or sticky video player rather than separate players per chapter.
* Show layered summary options near the top of the experience.
* Show smart chapters in a scrollable list below or beside the summary content.
* Make timestamps clearly clickable and easy to recognize.
* Keep transcript-heavy content collapsed by default to preserve readability.
* The interface should prioritize readability, simple navigation, and low cognitive load over visual complexity.

#### 9. Output Quality Requirements

* Clarity, conciseness, and correctness are the highest output priorities.
* Summary and chapter content should be understandable without reading the full transcript first.
* Generated claims should remain faithful to the transcript source.
* When possible, summary points and chapter points should be traceable to transcript evidence or corresponding time ranges.
* The system should avoid overstating confidence when the transcript source is low quality, incomplete, or ambiguous.

#### 10. Failure States And Edge Cases

The product must handle common failure scenarios explicitly and transparently.

##### Required Failure Handling

* **No transcript available:** Inform the user that the video cannot currently be processed and explain why if known.
* **Poor transcript quality:** Warn the user that summary/chapter quality may be reduced.
* **Very long video:** If the video exceeds the supported limit, reject it clearly or provide a partial-processing policy.
* **Non-supported language:** Inform the user if the detected language is outside the V1 supported language set.
* **Malformed focus prompt:** Ignore unsafe or unusable prompt input gracefully and continue with safe defaults or ask the user to revise it.
* **Rate limit or temporary service issue:** Return a retry-oriented message rather than a generic failure.
* **Partial extraction failure:** If transcript retrieval succeeds but one downstream feature fails, return the available output and label the missing portion clearly.

#### 11. Non-Functional Requirements

* For English-language videos up to 60 minutes long, the product should target time-to-first-result within 2 minutes and complete processing within 5 minutes under normal conditions.
* For English-language videos between 60 and 90 minutes long, the product should target time-to-first-result within 4 minutes and complete processing within 10 minutes under normal conditions.
* The system should support retries for transient failures where appropriate.
* The system should preserve processed source context for regeneration for the duration of the active user workflow.
* The product should set reasonable cost-awareness boundaries so repeated regenerations remain operationally viable.
* The UX should favor graceful degradation over total failure whenever part of the pipeline succeeds.

#### 12. Product-Level Acceptance And Validation

The V1 release should be validated against product-level checks, not only implementation completion.

##### Validation Expectations

* Timestamp seeking works reliably for generated chapters and lands within an acceptable tolerance of the intended chapter start.
* Chapter segmentation is coherent enough that adjacent chapters represent distinct topic units and the full list can be read as a sensible progression through the video.
* Layered summaries are distinct, readable, and faithful to the source transcript.
* Regeneration behavior is stable and does not trigger transcript re-ingestion for the same video during the active user workflow.
* Failure states are understandable and actionable, with clear next-step guidance where recovery is possible.

#### 13. Success Metrics

The initial MVP should be evaluated with a small set of practical success metrics:

* completion rate for submitted supported videos
* time to first readable result
* chapter timestamp click-through rate
* regenerate usage rate
* user-rated usefulness of summary output

#### 14. Out Of Scope For V1

The following capabilities are intentionally excluded from the MVP in order to keep the initial product focused and practical:

* Mind Maps
* Contextual Glossary
* Semantic Q&A / chat over transcript
* Action Item Extraction
* advanced prompt targeting by output type
* exclusion-rule prompt controls
* multi-source ingestion beyond YouTube
* built-in auto-transcription

#### 15. Future Versions And Product Direction

The broader VidSense vision remains relevant beyond V1. The following features are candidates for future versions once the MVP reading workflow proves useful and reliable:

##### Feature [Later]: Mind Maps

* Visual graph of concepts, people, and technologies discussed in the video.
* Potential interaction with chapters so users can jump from a concept to relevant sections.

##### Feature [Later]: Contextual Glossary

* Extraction of domain-specific terms and definitions grounded in the source content.

##### Feature [Later]: Semantic Q&A

* Conversational querying over the processed transcript with citations or grounded references.

##### Feature [Later]: Action Item Extraction

* Dedicated extraction mode for tutorials, workflows, and procedural videos.

#### 16. Editorial Guidance

This PRD should remain product-facing and outcome-focused. Technical architecture, vendor selection, schema enforcement mechanics, caching implementation, model orchestration, and visualization library choices should be documented separately in engineering design or technical specification documents.
