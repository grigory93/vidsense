import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TranscriptSourceType(str, enum.Enum):
    manual = "manual"
    auto_generated = "auto_generated"
    unknown = "unknown"


class AnalysisRunStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    complete = "complete"
    partial = "partial"
    failed = "failed"


class SummaryLevel(str, enum.Enum):
    thesis = "thesis"
    executive = "executive"
    detailed = "detailed"


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    youtube_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512))
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    language: Mapped[str | None] = mapped_column(String(10))
    thumbnail_url: Mapped[str | None] = mapped_column(String(512))
    channel_name: Mapped[str | None] = mapped_column(String(256))
    channel_url: Mapped[str | None] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    upload_date: Mapped[str | None] = mapped_column(String(20))
    view_count: Mapped[int | None] = mapped_column(Integer)
    like_count: Mapped[int | None] = mapped_column(Integer)
    tags_json: Mapped[str | None] = mapped_column(Text)
    top_comments_json: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    transcript_sources: Mapped[list["TranscriptSource"]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )
    analysis_runs: Mapped[list["AnalysisRun"]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )
    qa_messages: Mapped[list["QAMessage"]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )


class TranscriptSource(Base):
    __tablename__ = "transcript_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), nullable=False, index=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    segments_json: Mapped[str | None] = mapped_column(Text)  # JSON array of {text, start, duration}
    source_type: Mapped[TranscriptSourceType] = mapped_column(
        Enum(TranscriptSourceType), default=TranscriptSourceType.unknown
    )
    quality_signal: Mapped[str | None] = mapped_column(String(50))  # "good", "auto_generated", "poor"
    language_code: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    video: Mapped["Video"] = relationship(back_populates="transcript_sources")


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), nullable=False, index=True)
    focus_prompt: Mapped[str | None] = mapped_column(Text)
    status: Mapped[AnalysisRunStatus] = mapped_column(
        Enum(AnalysisRunStatus), default=AnalysisRunStatus.pending, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    current_step: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    video: Mapped["Video"] = relationship(back_populates="analysis_runs")
    summaries: Mapped[list["Summary"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="Chapter.sort_order",
    )
    mind_map: Mapped["MindMap | None"] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    glossary_terms: Mapped[list["GlossaryTerm"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="GlossaryTerm.sort_order",
    )


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False, index=True)
    level: Mapped[SummaryLevel] = mapped_column(Enum(SummaryLevel), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_json: Mapped[str | None] = mapped_column(Text)  # JSON for detailed outline points

    run: Mapped["AnalysisRun"] = relationship(back_populates="summaries")


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False, index=True)
    chapter_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    start_time_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    end_time_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_points_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array of strings
    transcript_segment: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    run: Mapped["AnalysisRun"] = relationship(back_populates="chapters")


class MindMap(Base):
    __tablename__ = "mind_maps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False, index=True)
    nodes_json: Mapped[str] = mapped_column(Text, nullable=False)
    edges_json: Mapped[str] = mapped_column(Text, nullable=False)

    run: Mapped["AnalysisRun"] = relationship(back_populates="mind_map")


class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False, index=True)
    term: Mapped[str] = mapped_column(String(256), nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    related_terms_json: Mapped[str | None] = mapped_column(Text)
    occurrences_json: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    run: Mapped["AnalysisRun"] = relationship(back_populates="glossary_terms")


class QAMessage(Base):
    __tablename__ = "qa_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    video: Mapped["Video"] = relationship(back_populates="qa_messages")
