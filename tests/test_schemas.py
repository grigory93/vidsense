"""Tests for Pydantic schema validation."""
import pytest
from pydantic import ValidationError

from app.models.schemas import (
    ChapterListSchema,
    ChapterSchema,
    GlossaryListSchema,
    GlossaryTermSchema,
    MindMapEdgeSchema,
    MindMapNodeSchema,
    MindMapSchema,
    SummarySchema,
    _seconds_to_mmss,
)


class TestChapterSchema:
    def _valid_chapter(self, **overrides):
        base = dict(
            chapter_id="ch_01",
            title="Introduction",
            start_time_sec=0,
            end_time_sec=120,
            summary="The speaker introduces the topic.",
            key_points=["Point A", "Point B"],
            transcript_segment="Hello everyone, welcome to the talk.",
        )
        base.update(overrides)
        return base

    def test_valid_chapter(self):
        ch = ChapterSchema(**self._valid_chapter())
        assert ch.chapter_id == "ch_01"
        assert ch.start_time_sec == 0
        assert ch.end_time_sec == 120

    def test_end_before_start_raises(self):
        with pytest.raises(ValidationError, match="end_time_sec"):
            ChapterSchema(**self._valid_chapter(start_time_sec=120, end_time_sec=60))

    def test_end_equals_start_raises(self):
        with pytest.raises(ValidationError):
            ChapterSchema(**self._valid_chapter(start_time_sec=60, end_time_sec=60))

    def test_empty_key_points_raises(self):
        with pytest.raises(ValidationError):
            ChapterSchema(**self._valid_chapter(key_points=[]))

    def test_negative_start_raises(self):
        with pytest.raises(ValidationError):
            ChapterSchema(**self._valid_chapter(start_time_sec=-1, end_time_sec=120))


class TestChapterListSchema:
    def test_empty_list_raises(self):
        with pytest.raises(ValidationError):
            ChapterListSchema(chapters=[])

    def test_single_chapter(self):
        ch = ChapterSchema(
            chapter_id="ch_01",
            title="Test",
            start_time_sec=0,
            end_time_sec=60,
            summary="S",
            key_points=["K"],
            transcript_segment="T",
        )
        result = ChapterListSchema(chapters=[ch])
        assert len(result.chapters) == 1


class TestSummarySchema:
    def test_valid_summary(self):
        s = SummarySchema(
            thesis="Short thesis.",
            executive="Medium executive summary.",
            detailed_outline=["Point 1", "Point 2"],
        )
        assert s.thesis == "Short thesis."
        assert len(s.detailed_outline) == 2

    def test_empty_outline_raises(self):
        with pytest.raises(ValidationError):
            SummarySchema(
                thesis="T",
                executive="E",
                detailed_outline=[],
            )


class TestMindMapNodeSchema:
    def test_valid_node(self):
        n = MindMapNodeSchema(
            node_id="n_01",
            label="Machine Learning",
            type="concept",
            description="A subfield of AI.",
            chapter_ids=["ch_01"],
        )
        assert n.node_id == "n_01"
        assert n.type == "concept"
        assert n.chapter_ids == ["ch_01"]

    def test_empty_chapter_ids_default(self):
        n = MindMapNodeSchema(
            node_id="n_01",
            label="Term",
            type="concept",
            description="Desc.",
        )
        assert n.chapter_ids == []


class TestMindMapEdgeSchema:
    def test_valid_edge(self):
        e = MindMapEdgeSchema(
            source="n_01",
            target="n_02",
            relationship="uses",
        )
        assert e.source == "n_01"
        assert e.target == "n_02"
        assert e.relationship == "uses"


class TestMindMapSchema:
    def test_valid_mind_map(self):
        nodes = [
            MindMapNodeSchema(
                node_id="n_01",
                label="Concept",
                type="concept",
                description="A concept.",
                chapter_ids=[],
            ),
        ]
        edges = [
            MindMapEdgeSchema(source="n_01", target="n_02", relationship="relates to"),
        ]
        m = MindMapSchema(nodes=nodes, edges=edges)
        assert len(m.nodes) == 1
        assert len(m.edges) == 1

    def test_empty_nodes_raises(self):
        with pytest.raises(ValidationError):
            MindMapSchema(nodes=[], edges=[])

    def test_edges_default_empty(self):
        nodes = [
            MindMapNodeSchema(
                node_id="n_01",
                label="X",
                type="concept",
                description="D",
                chapter_ids=[],
            ),
        ]
        m = MindMapSchema(nodes=nodes)
        assert m.edges == []


class TestGlossaryTermSchema:
    def test_valid_term(self):
        t = GlossaryTermSchema(
            term="API",
            definition="Application programming interface.",
            category="acronym",
            related_terms=["REST"],
        )
        assert t.term == "API"
        assert t.category == "acronym"
        assert t.related_terms == ["REST"]

    def test_related_terms_default_empty(self):
        t = GlossaryTermSchema(
            term="Term",
            definition="Def.",
            category="technical",
        )
        assert t.related_terms == []


class TestGlossaryListSchema:
    def test_valid_list(self):
        terms = [
            GlossaryTermSchema(
                term="API",
                definition="Application programming interface.",
                category="acronym",
                related_terms=[],
            ),
        ]
        g = GlossaryListSchema(terms=terms)
        assert len(g.terms) == 1
        assert g.terms[0].term == "API"

    def test_empty_terms_raises(self):
        with pytest.raises(ValidationError):
            GlossaryListSchema(terms=[])


class TestSecondsToMmss:
    def test_under_one_minute(self):
        assert _seconds_to_mmss(45) == "0:45"

    def test_one_minute(self):
        assert _seconds_to_mmss(60) == "1:00"

    def test_over_one_hour(self):
        assert _seconds_to_mmss(3661) == "1:01:01"

    def test_zero(self):
        assert _seconds_to_mmss(0) == "0:00"
