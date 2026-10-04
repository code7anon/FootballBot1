from __future__ import annotations
from dataclasses import dataclass
from math import exp, factorial
from datetime import datetime
import numpy as np
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from ..models import Fixture, Team, InjurySnapshot


@dataclass
class Probabilities:
    home: float
    draw: float
    away: float
    confidence: float
    model_name: str


def poisson_pmf(k: int, lam: float) -> float:
    return exp(-lam) * (lam ** k) / factorial(k)


def poisson_1x2(lam_home: float, lam_away: float) -> tuple[float, float, float]:
    matrix = np.array([
        [poisson_pmf(i, lam_home) * poisson_pmf(j, lam_away) for j in range(8)]
        for i in range(8)
    ])
    home = float(np.tril(matrix, -1).sum())
    draw = float(np.trace(matrix))
    away = float(np.triu(matrix, 1).sum())
    total = home + draw + away
    return home / total, draw / total, away / total


def team_form(db: Session, team_id: int, before: datetime, n: int = 5) -> dict:
    rows = db.scalars(select(Fixture).where(
        or_(Fixture.home_team_id == team_id, Fixture.away_team_id == team_id),
        Fixture.kickoff < before,
        Fixture.status.in_(["FT", "AET", "PEN"]),
    ).order_by(Fixture.kickoff.desc()).limit(n)).all()
    gf = ga = pts = 0
    for f in rows:
        if f.home_team_id == team_id:
            goals_for, goals_against = f.home_goals or 0, f.away_goals or 0
        else:
            goals_for, goals_against = f.away_goals or 0, f.home_goals or 0
        gf += goals_for
        ga += goals_against
        pts += 3 if goals_for > goals_against else 1 if goals_for == goals_against else 0
    count = max(len(rows), 1)
    return {"gf": gf / count, "ga": ga / count, "pts": pts / (3 * count), "n": len(rows)}


def elo_scores(db: Session, before: datetime) -> dict[int, float]:
    """Compute Elo for all teams once. This is the expensive part - do it only once per cycle."""
    rows = db.scalars(
        select(Fixture)
        .where(Fixture.kickoff < before, Fixture.status.in_(["FT", "AET", "PEN"]))
        .order_by(Fixture.kickoff)
    ).all()
    elo: dict[int, float] = {}
    for f in rows:
        a = elo.get(f.home_team_id, 1500.0)
        b = elo.get(f.away_team_id, 1500.0)
        expected_a = 1 / (1 + 10 ** ((b + 60 - a) / 400))
        hg, ag = f.home_goals or 0, f.away_goals or 0
        result_a = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
        k = 20 + min(abs(hg - ag), 3) * 3
        elo[f.home_team_id] = a + k * (result_a - expected_a)
        elo[f.away_team_id] = b + k * ((1 - result_a) - (1 - expected_a))
    return elo


def features_for_fixture(db: Session, f: Fixture, elo: dict[int, float]) -> dict:
    hf = team_form(db, f.home_team_id, f.kickoff)
    af = team_form(db, f.away_team_id, f.kickoff)
    e_h = elo.get(f.home_team_id, 1500.0)
    e_a = elo.get(f.away_team_id, 1500.0)

    home_inj = db.scalar(select(InjurySnapshot).where(
        InjurySnapshot.fixture_id == f.id,
    ).order_by(InjurySnapshot.captured_at.desc()).limit(1))
    away_inj = db.scalar(select(InjurySnapshot).where(
        InjurySnapshot.fixture_id == f.id,
    ).order_by(InjurySnapshot.captured_at.desc()).limit(1))

    return {
        "home_elo": e_h,
        "away_elo": e_a,
        "elo_diff": e_h - e_a,
        "home_gf5": hf["gf"],
        "home_ga5": hf["ga"],
        "home_pts5": hf["pts"],
        "away_gf5": af["gf"],
        "away_ga5": af["ga"],
        "away_pts5": af["pts"],
        "home_matches": hf["n"],
        "away_matches": af["n"],
        "home_injury_score": float(home_inj.severity_score if home_inj else 0.0),
        "away_injury_score": float(away_inj.severity_score if away_inj else 0.0),
    }


def predict_fixture(db: Session, f: Fixture, elo_cache: dict | None = None) -> Probabilities:
    """Fast prediction using Poisson + Elo. No training on every call."""
    elo = elo_cache if elo_cache is not None else elo_scores(db, f.kickoff)
    features = features_for_fixture(db, f, elo)

    lam_h = max(0.15, 1.35
                + 0.30 * (features["home_gf5"] - features["away_ga5"])
                + 0.0008 * features["elo_diff"]
                - 0.025 * features["home_injury_score"]
                + 0.010 * features["away_injury_score"])

    lam_a = max(0.15, 1.00
                + 0.30 * (features["away_gf5"] - features["home_ga5"])
                - 0.0002 * features["elo_diff"]
                - 0.025 * features["away_injury_score"]
                + 0.010 * features["home_injury_score"])

    p_h, p_d, p_a = poisson_1x2(lam_h, lam_a)

    confidence = min(0.65, 0.30 + 0.05 * min(features["home_matches"], features["away_matches"]))

    return Probabilities(p_h, p_d, p_a, confidence, "poisson-elo-v1")


def goal_markets(lam_h: float, lam_a: float) -> dict[str, float]:
    over = 0.0
    for h in range(8):
        for a in range(8):
            if h + a >= 3:
                over += poisson_pmf(h, lam_h) * poisson_pmf(a, lam_a)
    return {
        "OVER_2_5": min(max(over, 0.001), 0.999),
        "UNDER_2_5": min(max(1 - over, 0.001), 0.999),
    }