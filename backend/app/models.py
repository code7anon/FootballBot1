from datetime import datetime, date
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Date, Text, JSON, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    logo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Fixture(Base):
    __tablename__ = "fixtures"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    league_id: Mapped[int] = mapped_column(Integer, index=True)
    season: Mapped[int] = mapped_column(Integer, index=True)
    kickoff: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(20), default="NS")
    minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    home_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_fixture_kickoff_status", "kickoff", "status"),
    )


class MatchSnapshot(Base):
    __tablename__ = "match_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    home_shots: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_shots: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_sot: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_sot: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_possession: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_possession: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_corners: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_corners: Mapped[float | None] = mapped_column(Float, nullable=True)
    home_xg: Mapped[float | None] = mapped_column(Float, nullable=True)
    away_xg: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class InjurySnapshot(Base):
    __tablename__ = "injury_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), index=True)
    team_provider_id: Mapped[int] = mapped_column(Integer, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    player_count: Mapped[int] = mapped_column(Integer, default=0)
    key_players_out: Mapped[int] = mapped_column(Integer, default=0)
    severity_score: Mapped[float] = mapped_column(Float, default=0.0)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_provider_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    event_provider_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    bookmaker: Mapped[str] = mapped_column(String(120))
    market: Mapped[str] = mapped_column(String(80))
    selection: Mapped[str] = mapped_column(String(120))
    line: Mapped[float | None] = mapped_column(Float, nullable=True)
    odds: Mapped[float] = mapped_column(Float)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    market: Mapped[str] = mapped_column(String(80))
    selection: Mapped[str] = mapped_column(String(120))
    probability: Mapped[float] = mapped_column(Float)
    fair_odds: Mapped[float] = mapped_column(Float)
    model_name: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    features_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Bet(Base):
    __tablename__ = "bets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fixture_id: Mapped[int | None] = mapped_column(ForeignKey("fixtures.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="OPEN")
    mode: Mapped[str] = mapped_column(String(20), default="PAPER")
    market: Mapped[str] = mapped_column(String(80))
    selection: Mapped[str] = mapped_column(String(120))
    odds: Mapped[float] = mapped_column(Float)
    model_probability: Mapped[float] = mapped_column(Float)
    edge: Mapped[float] = mapped_column(Float)
    stake: Mapped[float] = mapped_column(Float)
    potential_payout: Mapped[float] = mapped_column(Float)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class BankrollEvent(Base):
    __tablename__ = "bankroll_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    amount: Mapped[float] = mapped_column(Float)
    balance_after: Mapped[float] = mapped_column(Float)
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class SystemState(Base):
    __tablename__ = "system_state"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value_json: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class JobRun(Base):
    __tablename__ = "job_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    job_type: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
