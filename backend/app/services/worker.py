from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select
from ..models import JobRun, Fixture, Prediction, SystemState
from ..services.thesportsdb import TheSportsDBProvider
from ..services.odds import OddsProvider
from ..services.model import predict_fixture, goal_markets
from ..services.edge import build_signals
from ..services.paper import PaperTrader
from ..config import get_settings

settings = get_settings()


def persist_predictions(db: Session, fixture: Fixture):
    probs = predict_fixture(db, fixture)
    db.add_all([
        Prediction(fixture_id=fixture.id, market="h2h", selection="HOME", probability=probs.home, fair_odds=1/max(probs.home, 0.001), model_name=probs.model_name, confidence=probs.confidence),
        Prediction(fixture_id=fixture.id, market="h2h", selection="DRAW", probability=probs.draw, fair_odds=1/max(probs.draw, 0.001), model_name=probs.model_name, confidence=probs.confidence),
        Prediction(fixture_id=fixture.id, market="h2h", selection="AWAY", probability=probs.away, fair_odds=1/max(probs.away, 0.001), model_name=probs.model_name, confidence=probs.confidence),
    ])
    return probs


async def run_cycle(db: Session) -> dict:
    run = JobRun(job_type="cycle", status="RUNNING")
    db.add(run)
    db.commit()
    db.refresh(run)
    details: dict = {}

    try:
        football = TheSportsDBProvider(db)
        odds = OddsProvider(db)

        if football.enabled:
            today = datetime.now(timezone.utc).date()
            daily_key = f"daily_fixture_sync:{today.isoformat()}"
            state = db.get(SystemState, daily_key)
            if not state:
                count = await football.sync_day(today)
                db.add(SystemState(key=daily_key, value_json={"synced": count}))
                details["today_fixtures"] = count
                db.commit()
            else:
                details["today_fixtures"] = state.value_json.get("synced", 0)
            try:
                live = await football.sync_live()
            except Exception as exc:
                live = 0
                details.setdefault("live_errors", []).append(str(exc))
            details["live_fixtures"] = live
        else:
            details["today_fixtures"] = 0
            details["live_fixtures"] = 0

        if odds.enabled:
            details["odds_rows"] = await odds.sync_odds()
        else:
            details["odds_rows"] = 0

        trader = PaperTrader(db)
        trader.ensure_bankroll()
        trader.settle_open()

        # Generate predictions for upcoming/live matches.
        now = datetime.utcnow()
        fixtures = db.scalars(
            select(Fixture)
            .where(Fixture.kickoff >= now - timedelta(hours=3), Fixture.kickoff <= now + timedelta(hours=24))
            .order_by(Fixture.kickoff)
            .limit(100)
        ).all()

        preds = 0
        bets = 0
        enriched = 0

        for fixture in fixtures:
            if fixture.status in {"FT", "AET", "PEN"}:
                continue

            p = persist_predictions(db, fixture)
            probabilities = {"home": p.home, "draw": p.draw, "away": p.away}
            signals = build_signals(db, fixture, probabilities, p.confidence)

            for s in signals:
                stake = trader.balance() * s.stake_pct
                if stake > 0:
                    bet = trader.place(
                        fixture,
                        s.market,
                        s.selection,
                        s.odds,
                        s.probability,
                        s.edge,
                        stake,
                        {"model": p.model_name, "confidence": p.confidence},
                    )
                    if bet:
                        bets += 1
            preds += 1

        db.commit()
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