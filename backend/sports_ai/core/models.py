from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RecommendationRow(Base):
    __tablename__ = "philthy_sports_ai_recommendations"
    __table_args__ = (
        Index("philthy_sports_ai_rec_event_idx", "sport", "event_id", "as_of"),
        Index("philthy_sports_ai_rec_asof_idx", "as_of"),
    )

    recommendation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sport: Mapped[str] = mapped_column(String(8), nullable=False)
    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    market: Mapped[str] = mapped_column(String(64), nullable=False)
    selection: Mapped[str] = mapped_column(Text, nullable=False)
    line: Mapped[float | None] = mapped_column(Float, nullable=True)
    offered_american: Mapped[float] = mapped_column(Float, nullable=False)
    fair_probability: Mapped[float] = mapped_column(Float, nullable=False)
    market_anchor_probability: Mapped[float] = mapped_column(Float, nullable=False)
    model_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge: Mapped[float] = mapped_column(Float, nullable=False)
    expected_value: Mapped[float] = mapped_column(Float, nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    probability_source: Mapped[str] = mapped_column(String(96), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ClosingSnapshotRow(Base):
    __tablename__ = "philthy_sports_ai_closing_snapshots"
    __table_args__ = (
        Index("philthy_sports_ai_close_rec_idx", "recommendation_id", "observed_at"),
    )

    record_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    recommendation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    close_american: Mapped[float] = mapped_column(Float, nullable=False)
    close_fair_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
