from __future__ import annotations
from datetime import datetime, date, timedelta
from fastapi import FastAPI, Depends, Header, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, distinct, update, text
from sqlalchemy.orm import Session
from pathlib import Path

from .config import get_settings
from .db import Base, engine, get_db
from .models import Fixture, Team, OddsSnapshot, Prediction, Bet, BankrollEvent, JobRun, SystemState
from .schemas import MatchOut, BetOut
from .services.worker import run_cycle
from .services.model import predict_fixture
from .services.paper import PaperTrader
from .services.football_data import FootballDataProvider

settings = get_settings()
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


def admin_guard(token: str | None):
    if not settings.admin_token or settings.admin_token == "change-me":
        return
    if token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")


@app.get("/api/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat(), "env": settings.env}


@app.get("/api/config")
def config():
    return {
        "paper_trading": settings.paper_trading,
        "tracked_leagues": settings.competition_codes,
        "season": settings.football_season,
        "odds_enabled": settings.odds_enabled and bool(settings.odds_api_key),
        "min_edge": settings.min_edge,
    }


@app.post("/api/admin/reset-db")
def reset_db(x_admin_token: str | None = Header(default=None)):
    admin_guard(x_admin_token)
    from .db import Base, engine
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return {"ok": True, "message": "Vse tabele so bile izbrisane in znova ustvarjene."}


@app.get("/api/matches")
def matches(day: str | None = None, db: Session = Depends(get_db)):
    target = date.fromisoformat(day) if day else datetime.utcnow().date()
    start = datetime.combine(target, datetime.min.time())
    end = start + timedelta(days=1)
    rows = db.scalars(
        select(Fixture)
        .where(Fixture.kickoff >= start, Fixture.kickoff < end)
        .order_by(Fixture.kickoff)
    ).all()
    result = []
    for f in rows:
        ht = db.get(Team, f.home_team_id)
        at = db.get(Team, f.away_team_id)
        result.append(MatchOut(
            id=f.id,
            provider_id=f.provider_id,
            league_id=f.league_id,
            kickoff=f.kickoff,
            status=f.status,
            minute=f.minute,
            home_team=ht.name if ht else str(f.home_team_id),
            away_team=at.name if at else str(f.away_team_id),
            home_goals=f.home_goals,
            away_goals=f.away_goals,
        ))
    return result


@app.get("/api/matches/upcoming")
def matches_upcoming(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    now = datetime.utcnow()
    rows = db.scalars(
        select(Fixture).where(Fixture.kickoff >= now).order_by(Fixture.kickoff).limit(limit)
    ).all()
    result = []
    for f in rows:
        ht = db.get(Team, f.home_team_id)
        at = db.get(Team, f.away_team_id)
        result.append({
            "id": f.id,
            "kickoff": f.kickoff.isoformat() if f.kickoff else None,
            "status": f.status,
            "league_id": f.league_id,
            "home_team": ht.name if ht else "?",
            "away_team": at.name if at else "?",
        })
    return result


@app.post("/api/admin/kill-connections")
def kill_connections(x_admin_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    admin_guard(x_admin_token)
    try:
        result = db.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid()"
        ))
        count = len(result.fetchall())
        db.commit()
        return {"ok": True, "terminated": count}
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, str(exc))


@app.get("/api/admin/odds-check")
def odds_check(x_admin_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    admin_guard(x_admin_token)
    total = db.scalar(text("SELECT COUNT(*) FROM odds_snapshots"))
    linked = db.scalar(text("SELECT COUNT(*) FROM odds_snapshots WHERE fixture_provider_id IS NOT NULL"))
    unlinked = db.scalar(text("SELECT COUNT(*) FROM odds_snapshots WHERE fixture_provider_id IS NULL"))
    distinct_fixtures = db.scalar(text("SELECT COUNT(DISTINCT fixture_provider_id) FROM odds_snapshots WHERE fixture_provider_id IS NOT NULL"))
    return {
        "total_odds": int(total or 0),
        "linked_to_fixture": int(linked or 0),
        "unlinked": int(unlinked or 0),
        "distinct_fixtures_with_odds": int(distinct_fixtures or 0),
    }

@app.get("/api/admin/fixtures-with-odds")
def fixtures_with_odds(x_admin_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    admin_guard(x_admin_token)
    rows = db.execute(text("""
        SELECT f.id, f.kickoff, f.status, f.home_team_id, f.away_team_id,
               COUNT(o.id) AS odds_count
        FROM fixtures f
        JOIN odds_snapshots o ON o.fixture_provider_id = f.provider_id
        GROUP BY f.id, f.kickoff, f.status, f.home_team_id, f.away_team_id
        ORDER BY f.kickoff
        LIMIT 30
    """)).all()
    result = []
    for r in rows:
        ht = db.get(Team, r[3])
        at = db.get(Team, r[4])
        result.append({
            "fixture_id": r[0],
            "kickoff": r[1].isoformat() if r[1] else None,
            "status": r[2],
            "home": ht.name if ht else "?",
            "away": at.name if at else "?",
            "odds_count": r[5],
        })
    return result


@app.get("/api/admin/upcoming-with-odds")
def upcoming_with_odds(x_admin_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Vrne samo prihajajoče tekme (kickoff >= now) z odds_count > 0."""
    admin_guard(x_admin_token)
    now = datetime.utcnow()
    rows = db.execute(text("""
        SELECT f.id, f.kickoff, f.status, f.home_team_id, f.away_team_id,
               COUNT(o.id) AS odds_count
        FROM fixtures f
        JOIN odds_snapshots o ON o.fixture_provider_id = f.provider_id
        WHERE f.kickoff >= :now AND f.status = 'NS'
        GROUP BY f.id, f.kickoff, f.status, f.home_team_id, f.away_team_id
        ORDER BY f.kickoff
        LIMIT 30
    """), {"now": now}).all()
    result = []
    for r in rows:
        ht = db.get(Team, r[3])
        at = db.get(Team, r[4])
        result.append({
            "fixture_id": r[0],
            "kickoff": r[1].isoformat() if r[1] else None,
            "status": r[2],
            "home": ht.name if ht else "?",
            "away": at.name if at else "?",
            "odds_count": r[5],
        })
    return result


@app.post("/api/admin/relink-odds")
def relink_odds(background_tasks: BackgroundTasks, x_admin_token: str | None = Header(default=None)):
    admin_guard(x_admin_token)
    background_tasks.add_task(_do_relink_odds)
    return {"ok": True, "message": "Relink started in background. Check /api/admin/relink-status"}


@app.get("/api/admin/relink-status")
def relink_status(x_admin_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    admin_guard(x_admin_token)
    state = db.get(SystemState, "relink_progress")
    return state.value_json if state else {"status": "idle"}


def _do_relink_odds():
    """Memory-safe relink: bulk update, brez nalaganja vseh kvot."""
    from .db import SessionLocal

    db = SessionLocal()
    state = None
    try:
        state = db.get(SystemState, "relink_progress")
        if not state:
            state = SystemState(key="relink_progress", value_json={})
            db.add(state)
            db.commit()

        state.value_json = {"status": "running", "started_at": datetime.utcnow().isoformat()}
        db.commit()

        teams_by_id = {t.id: t.name for t in db.scalars(select(Team)).all()}
        fixtures = db.scalars(
            select(Fixture).order_by(Fixture.kickoff.desc()).limit(100)
        ).all()

        def norm(s):
            if not s:
                return ""
            s = s.lower()
            for token in [" fc", " afc", " cf", " sc", " ac", "calcio ", " & ", " and ", "  "]:
                s = s.replace(token, " ")
            return "".join(c for c in s if c.isalnum() or c == " ").strip()

        def similarity(a, b):
            if not a or not b:
                return 0.0
            if a == b:
                return 1.0
            if a in b or b in a:
                return 0.9
            wa = set(a.split())
            wb = set(b.split())
            if not wa or not wb:
                return 0.0
            return len(wa & wb) / max(len(wa), len(wb))

        fixture_data = []
        for f in fixtures:
            th = teams_by_id.get(f.home_team_id, "")
            ta = teams_by_id.get(f.away_team_id, "")
            fixture_data.append({
                "id": f.provider_id,
                "h": norm(th),
                "a": norm(ta),
            })
        db.expunge_all()

        event_ids = db.scalars(
            select(distinct(OddsSnapshot.event_provider_id))
            .where(OddsSnapshot.fixture_provider_id.is_(None))
        ).all()
        event_ids = [e for e in event_ids if e]

        linked_total = 0
        processed = 0

        for event_id in event_ids:
            sample = db.scalar(
                select(OddsSnapshot)
                .where(OddsSnapshot.event_provider_id == event_id)
                .limit(1)
            )
            if not sample:
                continue

            raw = sample.raw_json or {}
            event = raw.get("event") or {}
            home_n = norm(event.get("home_team") or "")
            away_n = norm(event.get("away_team") or "")

            db.expunge(sample)

            if not home_n or not away_n:
                processed += 1
                continue

            best_id = None
            best_score = 0.0
            for fd in fixture_data:
                score = (similarity(home_n, fd["h"]) + similarity(away_n, fd["a"])) / 2
                if score > best_score:
                    best_score = score
                    best_id = fd["id"]

            if best_id and best_score >= 0.5:
                result = db.execute(
                    update(OddsSnapshot)
                    .where(OddsSnapshot.event_provider_id == event_id)
                    .where(OddsSnapshot.fixture_provider_id.is_(None))
                    .values(fixture_provider_id=best_id)
                )
                linked_total += result.rowcount or 0

            processed += 1
            db.expunge_all()

            if processed % 25 == 0:
                db.commit()
                state = db.get(SystemState, "relink_progress")
                if state:
                    state.value_json = {
                        "status": "running",
                        "processed": processed,
                        "total_events": len(event_ids),
                        "linked_so_far": linked_total,
                    }
                    db.commit()

        db.commit()
        state = db.get(SystemState, "relink_progress")
        if state:
            state.value_json = {
                "status": "done",
                "unique_events": len(event_ids),
                "linked_odds": linked_total,
                "finished_at": datetime.utcnow().isoformat(),
            }
            db.commit()

    except Exception as exc:
        try:
            db.rollback()
            state = db.get(SystemState, "relink_progress")
            if state:
                state.value_json = {"status": "failed", "error": str(exc)}
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@app.post("/api/admin/clear-predictions")
def clear_predictions(x_admin_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    admin_guard(x_admin_token)
    count = db.query(Prediction).delete()
    db.commit()
    return {"ok": True, "deleted": count}


@app.get("/api/matches/{fixture_id}")
def match_detail(fixture_id: int, db: Session = Depends(get_db)):
    f = db.get(Fixture, fixture_id)
    if not f:
        raise HTTPException(404, "Fixture not found")
    p = predict_fixture(db, f)
    ht = db.get(Team, f.home_team_id)
    at = db.get(Team, f.away_team_id)
    odds = db.scalars(
        select(OddsSnapshot)
        .where(OddsSnapshot.fixture_provider_id == f.provider_id)
        .order_by(OddsSnapshot.captured_at.desc())
        .limit(30)
    ).all()
    preds = db.scalars(
        select(Prediction)
        .where(Prediction.fixture_id == f.id)
        .order_by(Prediction.captured_at.desc())
        .limit(20)
    ).all()
    return {
        "fixture": MatchOut(
            id=f.id,
            provider_id=f.provider_id,
            league_id=f.league_id,
            kickoff=f.kickoff,
            status=f.status,
            minute=f.minute,
            home_team=ht.name if ht else "?",
            away_team=at.name if at else "?",
            home_goals=f.home_goals,
            away_goals=f.away_goals,
        ),
        "model": {"home": p.home, "draw": p.draw, "away": p.away, "confidence": p.confidence, "name": p.model_name},
        "odds": [
            {"bookmaker": o.bookmaker, "market": o.market, "selection": o.selection, "line": o.line, "odds": o.odds, "captured_at": o.captured_at}
            for o in odds
        ],
        "predictions": [
            {"market": x.market, "selection": x.selection, "probability": x.probability, "fair_odds": x.fair_odds, "confidence": x.confidence, "model_name": x.model_name}
            for x in preds
        ],
    }


@app.get("/api/bets")
def bets(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    return db.scalars(select(Bet).order_by(Bet.created_at.desc()).limit(limit)).all()


@app.get("/api/dashboard")
def dashboard(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    trader = PaperTrader(db)
    trader.ensure_bankroll()
    balance = trader.balance()
    since = datetime.utcnow() - timedelta(days=days)
    all_bets = db.scalars(select(Bet).where(Bet.created_at >= since).order_by(Bet.created_at.desc())).all()
    settled = [b for b in all_bets if b.pnl is not None]
    pnl = sum(b.pnl or 0 for b in settled)
    turnover = sum(b.stake for b in settled)
    wins = sum(1 for b in settled if b.status == "WON")
    open_bets = [b for b in all_bets if b.status == "OPEN"]
    avg_edge = sum(b.edge for b in all_bets) / len(all_bets) if all_bets else 0
    return {
        "bankroll": balance,
        "period_days": days,
        "pnl": pnl,
        "roi": pnl / turnover if turnover else 0,
        "bets": len(all_bets),
        "settled": len(settled),
        "wins": wins,
        "win_rate": wins / len(settled) if settled else 0,
        "avg_edge": avg_edge,
        "open_exposure": sum(b.stake for b in open_bets),
        "recent_bets": [
            {
                "id": b.id,
                "created_at": b.created_at,
                "status": b.status,
                "market": b.market,
                "selection": b.selection,
                "odds": b.odds,
                "model_probability": b.model_probability,
                "edge": b.edge,
                "stake": b.stake,
                "pnl": b.pnl,
            }
            for b in all_bets[:20]
        ],
    }


@app.post("/api/admin/run-cycle")
async def run_cycle_endpoint(x_admin_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    admin_guard(x_admin_token)
    try:
        return {"ok": True, "details": await run_cycle(db)}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.post("/api/admin/backfill")
async def backfill(competition_code: str, season: int | None = None, x_admin_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    admin_guard(x_admin_token)
    provider = FootballDataProvider(db)
    if not provider.enabled:
        raise HTTPException(400, "FOOTBALL_DATA_API_KEY is not configured")
    count = await provider.sync_season(competition_code, season)
    return {
        "ok": True,
        "competition_code": competition_code,
        "season": season or settings.football_season,
        "fixtures": count,
    }


@app.post("/api/admin/reset-paper")
def reset_paper(x_admin_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    admin_guard(x_admin_token)
    db.query(Bet).delete()
    db.query(BankrollEvent).delete()
    db.commit()
    trader = PaperTrader(db)
    trader.ensure_bankroll()
    return {"ok": True, "bankroll": trader.balance()}


@app.get("/api/admin/jobs")
def jobs(limit: int = 20, x_admin_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    admin_guard(x_admin_token)
    return db.scalars(select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)).all()


@app.get("/{full_path:path}")
def spa(full_path: str):
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "Frontend has not been built. Use the API at /docs."}