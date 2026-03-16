"""
Prompt templates for VidSense LLM pipeline.

Two families:
  - Summary prompts  → produce SummarySchema
  - Chapter prompts  → produce ChapterListSchema

Focus prompt injection uses a bounded <user_focus> marker so the model
adjusts emphasis without overriding core extraction instructions.
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

# ---------------------------------------------------------------------------
# Summary prompts
# ---------------------------------------------------------------------------

_SUMMARY_SYSTEM = """\
You are an expert at analysing video transcripts and producing structured, \
reader-friendly summaries. Your output must be grounded strictly in the \
provided transcript — do not introduce claims that are not supported by \
the source text.

Produce exactly three summary levels:

1. **thesis** — A concise 1-to-3 sentence summary capturing the single most \
important idea or takeaway from the video.

2. **executive** — A medium-length summary (3-6 paragraphs) that covers the \
main points, context, and conclusions. Written for someone who wants a solid \
understanding without watching the full video.

3. **detailed_outline** — A structured bullet-point outline (10-20 points) \
that captures the key ideas, arguments, and evidence in order of presentation.

Return your answer as a JSON object with exactly these three fields: \
"thesis" (string), "executive" (string), "detailed_outline" (array of strings).

Guidelines:
- Write for clarity and conciseness; avoid repetition across levels.
- Each level must be meaningfully more detailed than the previous one.
- Do not pad content to fill length targets.
"""

_SUMMARY_FOCUS_ADDON = """\

<user_focus>
The user has provided the following focus instruction. Emphasise content \
related to this topic throughout all three summary levels, but do not \
discard important context from the rest of the video:
{focus_prompt}
</user_focus>
"""

_SUMMARY_HUMAN = """\
Please summarise the following transcript:

<transcript>
{transcript}
</transcript>
"""


def build_summary_messages(transcript: str, focus_prompt: str | None = None) -> list:
    system_content = _SUMMARY_SYSTEM
    if focus_prompt and focus_prompt.strip():
        system_content += _SUMMARY_FOCUS_ADDON.format(focus_prompt=focus_prompt.strip())
    return [
        SystemMessage(content=system_content),
        HumanMessage(content=_SUMMARY_HUMAN.format(transcript=transcript)),
    ]


# ---------------------------------------------------------------------------
# Chapter prompts
# ---------------------------------------------------------------------------

_CHAPTER_SYSTEM = """\
You are an expert at segmenting video transcripts into logical, \
reader-friendly chapters. Your output must be grounded strictly in the \
provided transcript.

For each chapter, return a JSON object with exactly these fields:
- "chapter_id": a unique string identifier, e.g. "ch_01", "ch_02", ...
- "title": a concise chapter heading (5-10 words)
- "start_time_sec": integer start time in seconds (from the transcript timestamps)
- "end_time_sec": integer end time in seconds
- "summary": a 2-4 sentence summary of what happens in this chapter
- "key_points": an array of 2-5 bullet-point strings capturing the most \
important ideas in this chapter
- "transcript_segment": the verbatim transcript text that corresponds to \
this chapter

Return a JSON object with a single key "chapters" whose value is an array \
of chapter objects ordered chronologically.

Guidelines:
- Cover the entire video from beginning to end with no major unexplained gaps.
- Each chapter should represent a coherent topic unit; avoid trivially small \
  or trivially large chapters.
- start_time_sec must always be less than end_time_sec.
- chapter_id values must be unique within the list.
- The transcript_segment should be the actual text from the source, not a \
  paraphrase.
"""

_CHAPTER_FOCUS_ADDON = """\

<user_focus>
The user has provided the following focus instruction. When segmenting, \
prefer chapter boundaries that make the content related to this topic \
easy to navigate:
{focus_prompt}
</user_focus>
"""

_CHAPTER_HUMAN = """\
Please segment the following transcript into chapters. Each segment entry \
has the format: [start_sec] text

<transcript>
{transcript}
</transcript>
"""

_CHAPTER_HUMAN_CHUNKED = """\
This is chunk {chunk_index} of {total_chunks} of the transcript \
(video time {start_time} – {end_time}).

Please segment this chunk into chapters. Use the same JSON schema as usual. \
The start/end times are absolute seconds from the beginning of the video.

<transcript>
{transcript}
</transcript>
"""


def build_chapter_messages(transcript: str, focus_prompt: str | None = None) -> list:
    system_content = _CHAPTER_SYSTEM
    if focus_prompt and focus_prompt.strip():
        system_content += _CHAPTER_FOCUS_ADDON.format(focus_prompt=focus_prompt.strip())
    return [
        SystemMessage(content=system_content),
        HumanMessage(content=_CHAPTER_HUMAN.format(transcript=transcript)),
    ]


def build_chapter_messages_chunk(
    transcript: str,
    chunk_index: int,
    total_chunks: int,
    start_time: str,
    end_time: str,
    focus_prompt: str | None = None,
) -> list:
    system_content = _CHAPTER_SYSTEM
    if focus_prompt and focus_prompt.strip():
        system_content += _CHAPTER_FOCUS_ADDON.format(focus_prompt=focus_prompt.strip())
    return [
        SystemMessage(content=system_content),
        HumanMessage(
            content=_CHAPTER_HUMAN_CHUNKED.format(
                chunk_index=chunk_index,
                total_chunks=total_chunks,
                start_time=start_time,
                end_time=end_time,
                transcript=transcript,
            )
        ),
    ]


# ---------------------------------------------------------------------------
# Transcript formatting helpers
# ---------------------------------------------------------------------------


def format_transcript_with_timestamps(segments: list[dict]) -> str:
    """
    Format segments as: [start_sec] text
    Makes timestamps visible to the LLM for chapter time binding.
    """
    lines = []
    for seg in segments:
        start = int(seg.get("start", 0))
        text = seg.get("text", "").strip()
        if text:
            lines.append(f"[{start}] {text}")
    return "\n".join(lines)


def chunk_segments(
    segments: list[dict],
    max_chars: int = 40_000,
    overlap_chars: int = 2_000,
) -> list[list[dict]]:
    """
    Split segments into chunks of approximately max_chars characters,
    with an overlap window to preserve context at chunk boundaries.
    Used for long transcripts (60-90 min videos).
    """
    chunks: list[list[dict]] = []
    current_chunk: list[dict] = []
    current_len = 0

    for seg in segments:
        text_len = len(seg.get("text", ""))
        if current_len + text_len > max_chars and current_chunk:
            chunks.append(current_chunk)
            # Keep last N chars worth of segments as overlap
            overlap: list[dict] = []
            overlap_len = 0
            for s in reversed(current_chunk):
                s_len = len(s.get("text", ""))
                if overlap_len + s_len > overlap_chars:
                    break
                overlap.insert(0, s)
                overlap_len += s_len
            current_chunk = overlap
            current_len = overlap_len
        current_chunk.append(seg)
        current_len += text_len

    if current_chunk:
        chunks.append(current_chunk)

    return chunks
