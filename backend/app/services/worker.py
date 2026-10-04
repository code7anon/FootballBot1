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

        # 5. Prednostno obdelaj tekme, ki imajo kvote (365 dni naprej)
        from sqlalchemy import text, distinct

        fixtures_with_odds_ids = set(
            r[0] for r in db.execute(text("""
                SELECT DISTINCT fixture_provider_id
                FROM odds_snapshots
                WHERE fixture_provider_id IS NOT NULL
            """)).all()
        )
        details["fixtures_with_odds_total"] = len(fixtures_with_odds_ids)

        # Vse prihajajoče tekme (365 dni naprej)
        upcoming = db.scalars(
            select(Fixture)
            .where(Fixture.kickoff >= now)
            .where(Fixture.kickoff <= now + timedelta(days=365))
            .where(Fixture.status == "NS")
            .order_by(Fixture.kickoff)
            .limit(500)
        ).all()

        # Razvrsti: najprej tiste z kvotami, nato ostale
        with_odds = [f for f in upcoming if f.provider_id in fixtures_with_odds_ids]
        without_odds = [f for f in upcoming if f.provider_id not in fixtures_with_odds_ids]
        fixtures = with_odds[:30] + without_odds[:5]
        details["fixtures_selected"] = len(fixtures)
        details["fixtures_with_odds"] = len(with_odds)

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