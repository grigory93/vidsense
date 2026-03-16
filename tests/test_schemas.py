"""Tests for Pydantic schema validation."""
import pytest
from pydantic import ValidationError

from app.models.schemas import (
    ChapterListSchema,
    ChapterSchema,
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


class TestSecondsToMmss:
    def test_under_one_minute(self):
        assert _seconds_to_mmss(45) == "0:45"

    def test_one_minute(self):
        assert _seconds_to_mmss(60) == "1:00"

    def test_over_one_hour(self):
        assert _seconds_to_mmss(3661) == "1:01:01"

    def test_zero(self):
        assert _seconds_to_mmss(0) == "0:00"
