from __future__ import annotations
from datetime import datetime, date, timedelta
from fastapi import FastAPI, Depends, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from pathlib import Path

from .config import get_settings
from .db import Base, engine, get_db
from .models import Fixture, Team, OddsSnapshot, Prediction, Bet, BankrollEvent, JobRun
from .schemas import MatchOut, BetOut
from .services.worker import run_cycle
from .services.model import predict_fixture
from .services.paper import PaperTrader
from .services.thesportsdb import TheSportsDBProvider

settings = get_settings()
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors or ["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

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
        "tracked_leagues": settings.leagues_ids,
        "season": settings.football_season,
        "odds_enabled": settings.odds_enabled and bool(settings.odds_api_key),
        "min_edge": settings.min_edge,
    }

@app.post("/api/admin/reset-db")
def reset_db(x_admin_token: str | None = Header(default=None)):
    admin_guard(x_admin_token)
    from .db import Base, engine
    # To pobriše VSE tabele in jih znova ustvari (prazne)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return {"ok": True, "message": "Vse tabele so bile izbrisane in znova ustvarjene."}

@app.get("/api/matches")
def matches(day: str | None = None, db: Session = Depends(get_db)):
    target = date.fromisoformat(day) if day else datetime.utcnow().date()
    start = datetime.combine(target, datetime.min.time())
    end = start + timedelta(days=1)
    rows = db.scalars(select(Fixture).where(Fixture.kickoff >= start, Fixture.kickoff < end).order_by(Fixture.kickoff)).all()
    result = []
    for f in rows:
        ht = db.get(Team, f.home_team_id); at = db.get(Team, f.away_team_id)
        result.append(MatchOut(id=f.id, provider_id=f.provider_id, league_id=f.league_id, kickoff=f.kickoff, status=f.status, minute=f.minute, home_team=ht.name if ht else str(f.home_team_id), away_team=at.name if at else str(f.away_team_id), home_goals=f.home_goals, away_goals=f.away_goals))
    return result


@app.get("/api/matches/{fixture_id}")
def match_detail(fixture_id: int, db: Session = Depends(get_db)):
    f = db.get(Fixture, fixture_id)
    if not f: raise HTTPException(404, "Fixture not found")
    p = predict_fixture(db, f)
    ht = db.get(Team, f.home_team_id); at = db.get(Team, f.away_team_id)
    odds = db.scalars(select(OddsSnapshot).where(OddsSnapshot.fixture_provider_id == f.provider_id).order_by(OddsSnapshot.captured_at.desc()).limit(30)).all()
    preds = db.scalars(select(Prediction).where(Prediction.fixture_id == f.id).order_by(Prediction.captured_at.desc()).limit(20)).all()
    return {
        "fixture": MatchOut(id=f.id, provider_id=f.provider_id, league_id=f.league_id, kickoff=f.kickoff, status=f.status, minute=f.minute, home_team=ht.name if ht else "?", away_team=at.name if at else "?", home_goals=f.home_goals, away_goals=f.away_goals),
        "model": {"home": p.home, "draw": p.draw, "away": p.away, "confidence": p.confidence, "name": p.model_name},
        "odds": [{"bookmaker": o.bookmaker, "market": o.market, "selection": o.selection, "line": o.line, "odds": o.odds, "captured_at": o.captured_at} for o in odds],
        "predictions": [{"market": x.market, "selection": x.selection, "probability": x.probability, "fair_odds": x.fair_odds, "confidence": x.confidence, "model_name": x.model_name} for x in preds],
    }


@app.get("/api/bets")
def bets(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    return db.scalars(select(Bet).order_by(Bet.created_at.desc()).limit(limit)).all()


@app.get("/api/dashboard")
def dashboard(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    trader = PaperTrader(db); trader.ensure_bankroll(); balance = trader.balance()
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
        "recent_bets": [{
            "id": b.id, "created_at": b.created_at, "status": b.status, "market": b.market,
            "selection": b.selection, "odds": b.odds, "model_probability": b.model_probability,
            "edge": b.edge, "stake": b.stake, "pnl": b.pnl
        } for b in all_bets[:20]],
    }


@app.post("/api/admin/run-cycle")
async def run_cycle_endpoint(x_admin_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    admin_guard(x_admin_token)
    try:
        return {"ok": True, "details": await run_cycle(db)}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.post("/api/admin/backfill")
async def backfill(league_id: str, season: str | None = None, x_admin_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    admin_guard(x_admin_token)
    provider = TheSportsDBProvider(db)
    if not provider.enabled:
        raise HTTPException(400, "THESPORTSDB_API_KEY is not configured")
    count = await provider.sync_season(league_id, season)
    return {
        "ok": True,
        "league_id": league_id,
        "season": season or settings.football_season,
        "fixtures": count,
    }
@app.post("/api/admin/enrich/{fixture_id}")
async def enrich(fixture_id: int, x_admin_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    admin_guard(x_admin_token)
    provider = FootballProvider(db)
    if not provider.enabled:
        raise HTTPException(400, "API_FOOTBALL_KEY is not configured")
    teams = await provider.enrich_fixture_injuries(fixture_id)
    return {"ok": True, "team_snapshots": teams}

@app.post("/api/admin/reset-paper")
def reset_paper(x_admin_token: str | None = Header(default=None), db: Session = Depends(get_db)):
    admin_guard(x_admin_token)
    db.query(Bet).delete()
    db.query(BankrollEvent).delete()
    db.commit()
    trader = PaperTrader(db); trader.ensure_bankroll()
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
