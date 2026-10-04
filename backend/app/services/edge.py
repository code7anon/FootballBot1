from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from ..config import get_settings
from ..models import OddsSnapshot, Fixture, Prediction, Bet

settings = get_settings()


@dataclass
class EdgeSignal:
    fixture_id: int
    market: str
    selection: str
    odds: float
    probability: float
    fair_odds: float
    edge: float
    stake_pct: float
    confidence: float


def implied_probability(odds: float) -> float:
    return 1 / odds if odds > 1 else 1.0


def kelly_fraction(probability: float, odds: float) -> float:
    b = odds - 1
    q = 1 - probability
    raw = (b * probability - q) / b if b > 0 else 0.0
    return max(0.0, raw)


def build_signals(db: Session, fixture: Fixture, probabilities: dict[str, float], confidence: float) -> list[EdgeSignal]:
    latest = db.scalars(select(OddsSnapshot).where(
        OddsSnapshot.fixture_provider_id == fixture.provider_id,
        OddsSnapshot.captured_at >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    ).order_by(OddsSnapshot.captured_at.desc()).limit(100)).all()
    signals: list[EdgeSignal] = []
    mapping = {
        "home": ("h2h", "HOME"),
        "draw": ("h2h", "DRAW"),
        "away": ("h2h", "AWAY"),
    }
    team_names = {}
    try:
        from ..models import Team
        team_names["home"] = db.get(Team, fixture.home_team_id).name
        team_names["away"] = db.get(Team, fixture.away_team_id).name
    except Exception:
        pass

    seen = set()
    for row in latest:
        if row.market == "h2h":
            outcome = None
            if row.selection == team_names.get("home"): outcome = "home"
            elif row.selection == team_names.get("away"): outcome = "away"
            else:
                s = row.selection.lower()
                if s in {"home", "draw", "away"}: outcome = s
            if outcome and outcome not in seen:
                p = probabilities[outcome]
                edge = p - implied_probability(row.odds)
                if edge >= settings.min_edge:
                    k = kelly_fraction(p, row.odds) * settings.kelly_fraction
                    stake_pct = min(settings.max_stake_pct, max(0.0, k))
                    signals.append(EdgeSignal(fixture.id, "h2h", row.selection, row.odds, p, 1 / p, edge, stake_pct, confidence))
                    seen.add(outcome)
        elif row.market == "totals" and row.line is not None:
            key = "OVER_2_5" if row.selection.lower().startswith("over") and abs(float(row.line) - 2.5) < 0.01 else "UNDER_2_5" if row.selection.lower().startswith("under") and abs(float(row.line) - 2.5) < 0.01 else None
            if key and key in probabilities:
                p = probabilities[key]
                edge = p - implied_probability(row.odds)
                if edge >= settings.min_edge:
                    k = kelly_fraction(p, row.odds) * settings.kelly_fraction
                    stake_pct = min(settings.max_stake_pct, max(0.0, k))
                    signals.append(EdgeSignal(fixture.id, "totals", row.selection, row.odds, p, 1 / p, edge, stake_pct, confidence))
    return signals
