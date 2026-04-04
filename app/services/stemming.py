"""
Lightweight heuristic suffix-stripping for glossary-to-timestamp matching.

This is NOT a linguistic stemming library.  It improves recall for tier-3
(stem-based) matching in ``_find_term_occurrences`` but does not claim broad
morphological correctness.  Tiers 1 (exact match) and 2 (sliding window)
remain the primary strategies and work for any language without stemming.

Design:
  - ``Stemmer`` strips the first matching suffix if the remaining stem meets
    a minimum length, preventing over-stripping of short roots.
  - ``_REGISTRY`` maps normalized ISO 639-1 codes to per-language instances.
  - ``get_stemmer(language_code)`` returns the appropriate stemmer or a no-op
    fallback for unregistered languages.
"""
from __future__ import annotations

from app.lang import normalize_language_code


class Stemmer:
    """Suffix-stripping heuristic for a single language."""

    __slots__ = ("suffixes", "min_stem_len")

    def __init__(self, suffixes: tuple[str, ...], *, min_stem_len: int = 3) -> None:
        self.suffixes = suffixes
        self.min_stem_len = min_stem_len

    def stem(self, word: str) -> str:
        for suffix in self.suffixes:
            if len(word) > len(suffix) + self.min_stem_len and word.endswith(suffix):
                return word[: -len(suffix)]
        return word


_FALLBACK = Stemmer(())

_REGISTRY: dict[str, Stemmer] = {
    "en": Stemmer((
        "ation", "izing", "ised", "ized", "ting", "ning",
        "sion", "ment", "ness", "ally", "ious", "ical",
        "ies", "ing", "ion", "ous", "ive", "ble",
        "ers", "est", "ful", "ity", "ual",
        "ly", "ed", "er", "al", "es", "s",
    ), min_stem_len=2),
    "es": Stemmer((
        "amiento", "imiento", "ación", "mente", "idad", "ismo",
        "ando", "endo", "ción", "sión",
        "oso", "osa", "ble", "ivo", "iva",
        "ado", "ido", "nte",
        "ar", "er", "ir", "es", "os", "as", "s",
    )),
    "de": Stemmer((
        "ungen", "keit", "heit", "lich", "isch",
        "ung", "bar", "sam", "igt", "ier",
        "ig", "en", "er", "em", "es", "el", "e",
    )),
    "fr": Stemmer((
        "issement", "ement", "ation", "ition",
        "ment", "tion", "ique", "euse", "eur", "eux",
        "ant", "ent", "ire", "oir",
        "er", "ir", "és", "ée", "es", "é", "e", "s",
    )),
    "it": Stemmer((
        "amento", "imento", "zione", "mente",
        "ando", "endo", "bile", "oso", "osa",
        "ato", "ito", "nte", "ivo", "iva",
        "are", "ere", "ire",
        "ai", "ei", "he", "hi",
        "i", "o", "a", "e",
    )),
    "pt": Stemmer((
        "amento", "imento", "mente", "ação", "ções",
        "ando", "endo", "indo", "ável", "ível",
        "ade", "oso", "osa",
        "ado", "ido", "nte",
        "ar", "er", "ir", "os", "as", "es", "s",
    )),
    "ru": Stemmer((
        "ующий", "ивший",
        "ение", "ание", "ость", "ство", "ител",
        "ных", "ным", "ной", "ного",
        "ать", "ять", "ить", "еть",
        "ий", "ый", "ая", "ое", "ие",
        "ов", "ев", "ей", "ам", "ях",
        "ь", "и", "а", "о", "е", "у", "ы",
    ), min_stem_len=3),
    "uk": Stemmer((
        "ючий", "ючій",
        "ення", "ання", "ість", "ство", "ител",
        "них", "ним", "ній", "ного",
        "ати", "яти", "ити", "іти",
        "ія", "ій", "ий", "ая", "оє", "іє",
        "ів", "ей", "ам", "ях",
        "ь", "і", "а", "о", "е", "у", "и", "я",
    ), min_stem_len=3),
}


def get_stemmer(language_code: str) -> Stemmer:
    """Return the stemmer for *language_code*, or a no-op fallback."""
    norm = normalize_language_code(language_code)
    return _REGISTRY.get(norm, _FALLBACK)
