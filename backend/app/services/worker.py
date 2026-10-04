from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select
from ..models import JobRun, Fixture, Prediction, SystemState
from ..services.football_data import FootballDataProvider
from ..services.odds import OddsProvider
from ..services.model import predict_fixture, elo_scores
from ..services.edge import build_signals
from ..services.paper import PaperTrader
from ..config import get_settings

settings = get_settings()


async def run_cycle(db: Session) -> dict:
    run = JobRun(job_type="cycle", status="RUNNING")
    db.add(run)
    db.commit()
    db.refresh(run)
    details: dict = {}

    try:
        football = FootballDataProvider(db)
        odds = OddsProvider(db)

        # 1. Sync today's fixtures (if any)
        if football.enabled:
            today = datetime.now(timezone.utc).date()
            daily_key = f"daily_fixture_sync:{today.isoformat()}"
            state = db.get(SystemState, daily_key)
            if not state:
                try:
                    count = await football.sync_day(today)
                except Exception as exc:
                    count = 0
                    details.setdefault("sync_errors", []).append(str(exc))
                db.add(SystemState(key=daily_key, value_json={"synced": count}))
                details["today_fixtures"] = count
                db.commit()
            else:
                details["today_fixtures"] = state.value_json.get("synced", 0)
        else:
            details["today_fixtures"] = 0

        # 2. Sync odds (if enabled)
        if odds.enabled:
            try:
                details["odds_rows"] = await odds.sync_odds()
            except Exception as exc:
                details["odds_rows"] = 0
                details.setdefault("odds_errors", []).append(str(exc))
        else:
            details["odds_rows"] = 0

        # 3. Paper trader setup
        trader = PaperTrader(db)
        trader.ensure_bankroll()
        trader.settle_open()

        # 4. Compute Elo ONCE for all teams
        now = datetime.utcnow()
        elo_cache = elo_scores(db, now)
        details["elo_teams"] = len(elo_cache)

        # 5. Select ONLY 15 upcoming fixtures (fast)
        fixtures = db.scalars(
            select(Fixture)
            .where(Fixture.kickoff >= now)
            .where(Fixture.kickoff <= now + timedelta(days=30))
            .where(Fixture.status == "NS")
            .order_by(Fixture.kickoff)
            .limit(15)
        ).all()
        details["fixtures_selected"] = len(fixtures)

        preds = 0
        bets = 0

        for fixture in fixtures:
            try:
                # Skip if already predicted
                existing = db.scalar(
                    select(Prediction).where(Prediction.fixture_id == fixture.id).limit(1)
                )
                if existing:
                    continue

                probs = predict_fixture(db, fixture, elo_cache)

                db.add_all([
                    Prediction(fixture_id=fixture.id, market="h2h", selection="HOME",
                               probability=probs.home, fair_odds=1 / max(probs.home, 0.001),
                               model_name=probs.model_name, confidence=probs.confidence),
                    Prediction(fixture_id=fixture.id, market="h2h", selection="DRAW",
                               probability=probs.draw, fair_odds=1 / max(probs.draw, 0.001),
                               model_name=probs.model_name, confidence=probs.confidence),
                    Prediction(fixture_id=fixture.id, market="h2h", selection="AWAY",
                               probability=probs.away, fair_odds=1 / max(probs.away, 0.001),
                               model_name=probs.model_name, confidence=probs.confidence),
                ])
                db.flush()

                probabilities = {"home": probs.home, "draw": probs.draw, "away": probs.away}
                signals = build_signals(db, fixture, probabilities, probs.confidence)

                for s in signals:
                    stake = trader.balance() * s.stake_pct
                    if stake > 0:
                        bet = trader.place(
                            fixture, s.market, s.selection, s.odds,
                            s.probability, s.edge, stake,
                            {"model": probs.model_name, "confidence": probs.confidence},
                        )
                        if bet:
                            bets += 1
                preds += 1
                db.commit()
            except Exception as exc:
                details.setdefault("errors", []).append(f"fixture {fixture.id}: {exc}")
                db.rollback()
                continue

        details["predicted_fixtures"] = preds
        details["paper_bets_created"] = bets

        run.status = "SUCCESS"
        run.finished_at = datetime.utcnow()
        run.details = details
        db.commit()
        return details

    except Exception as exc:
        run.status = "FAILED"
        run.finished_at = datetime.utcnow()
        run.details = {"error": str(exc), **details}
        db.commit()
        raise