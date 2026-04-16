"""
Shared language-code utilities for VidSense.

Provides canonical normalization, display-name lookup, and the language-hint
block appended to LLM system prompts for non-English transcripts.
"""

from __future__ import annotations

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "de": "German",
    "fr": "French",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "uk": "Ukrainian",
    "nl": "Dutch",
    "pl": "Polish",
    "cs": "Czech",
    "sv": "Swedish",
    "da": "Danish",
    "no": "Norwegian",
    "fi": "Finnish",
    "tr": "Turkish",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "ar": "Arabic",
    "hi": "Hindi",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "th": "Thai",
    "el": "Greek",
    "ro": "Romanian",
    "hu": "Hungarian",
    "bg": "Bulgarian",
    "hr": "Croatian",
    "sk": "Slovak",
    "sr": "Serbian",
    "ca": "Catalan",
    "he": "Hebrew",
}


def normalize_language_code(code: str | None) -> str:
    """Normalize a language code to a bare ISO 639-1 lowercase tag.

    ``"pt-BR"`` → ``"pt"``, ``"en-US"`` → ``"en"``, ``None`` → ``"en"``.
    """
    if not code or not isinstance(code, str):
        return "en"
    stripped = code.strip().split("-")[0].split("_")[0].lower()
    return stripped or "en"


def language_display_name(code: str) -> str:
    """Human-readable name for a normalized language code."""
    norm = normalize_language_code(code)
    return LANGUAGE_NAMES.get(norm, norm)
