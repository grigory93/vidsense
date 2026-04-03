"""Tests for app.services.stemming — per-language heuristic suffix stripping."""
import pytest

from app.services.stemming import Stemmer, get_stemmer


class TestStemmerClass:
    def test_strips_matching_suffix(self):
        s = Stemmer(("ing", "ed"), min_stem_len=3)
        assert s.stem("running") == "runn"

    def test_no_match_returns_original(self):
        s = Stemmer(("ing",), min_stem_len=3)
        assert s.stem("hello") == "hello"

    def test_min_stem_len_prevents_over_strip(self):
        s = Stemmer(("ing",), min_stem_len=3)
        # "sing" -> stem would be "s" (len 1 < min_stem_len 3), so no strip
        assert s.stem("sing") == "sing"

    def test_empty_suffixes_returns_original(self):
        s = Stemmer(())
        assert s.stem("anything") == "anything"


class TestGetStemmer:
    def test_returns_english_stemmer(self):
        s = get_stemmer("en")
        assert s.stem("algorithms") == "algorithm"

    def test_returns_fallback_for_unknown(self):
        s = get_stemmer("xx")
        assert s.stem("anything") == "anything"

    def test_normalizes_region_code(self):
        s = get_stemmer("en-US")
        assert s.stem("algorithms") == "algorithm"


class TestEnglishStemmer:
    """Verify the English stemmer matches the original _crude_stem behaviour."""

    @pytest.fixture()
    def stemmer(self):
        return get_stemmer("en")

    @pytest.mark.parametrize("word,expected", [
        ("algorithms", "algorithm"),
        ("optimization", "optimiz"),
        ("processing", "process"),
        ("running", "runn"),
        ("carefully", "careful"),
        ("happiness", "happi"),
        ("educational", "education"),
    ])
    def test_positive_pairs(self, stemmer, word, expected):
        assert stemmer.stem(word) == expected

    @pytest.mark.parametrize("word", [
        "an",    # too short
        "go",    # too short
        "cat",   # no matching suffix
    ])
    def test_negative_pairs(self, stemmer, word):
        assert stemmer.stem(word) == word


class TestSpanishStemmer:
    @pytest.fixture()
    def stemmer(self):
        return get_stemmer("es")

    @pytest.mark.parametrize("word,expected", [
        ("organizaciones", "organizacion"),
        ("rápidamente", "rápida"),
        ("habilidad", "habil"),
    ])
    def test_positive_pairs(self, stemmer, word, expected):
        assert stemmer.stem(word) == expected

    @pytest.mark.parametrize("word", ["sol", "de"])
    def test_negative_pairs(self, stemmer, word):
        assert stemmer.stem(word) == word


class TestGermanStemmer:
    @pytest.fixture()
    def stemmer(self):
        return get_stemmer("de")

    @pytest.mark.parametrize("word,expected", [
        ("verarbeitung", "verarbeit"),
        ("freundlichkeit", "freundlich"),
        ("wissenschaftlich", "wissenschaft"),
    ])
    def test_positive_pairs(self, stemmer, word, expected):
        assert stemmer.stem(word) == expected

    @pytest.mark.parametrize("word", ["und", "ja"])
    def test_negative_pairs(self, stemmer, word):
        assert stemmer.stem(word) == word


class TestFrenchStemmer:
    @pytest.fixture()
    def stemmer(self):
        return get_stemmer("fr")

    @pytest.mark.parametrize("word,expected", [
        ("établissement", "établ"),
        ("organisation", "organis"),
    ])
    def test_positive_pairs(self, stemmer, word, expected):
        assert stemmer.stem(word) == expected


class TestRussianStemmer:
    @pytest.fixture()
    def stemmer(self):
        return get_stemmer("ru")

    @pytest.mark.parametrize("word,expected", [
        ("обучение", "обуч"),
        ("организации", "организаци"),
        ("качество", "каче"),
    ])
    def test_positive_pairs(self, stemmer, word, expected):
        assert stemmer.stem(word) == expected

    @pytest.mark.parametrize("word", ["да", "он"])
    def test_negative_pairs(self, stemmer, word):
        assert stemmer.stem(word) == word


class TestUkrainianStemmer:
    @pytest.fixture()
    def stemmer(self):
        return get_stemmer("uk")

    @pytest.mark.parametrize("word,expected", [
        ("навчання", "навч"),
        ("організація", "організац"),  # strips "ія" suffix
    ])
    def test_positive_pairs(self, stemmer, word, expected):
        assert stemmer.stem(word) == expected

    @pytest.mark.parametrize("word", ["так", "ні"])
    def test_negative_pairs(self, stemmer, word):
        assert stemmer.stem(word) == word
