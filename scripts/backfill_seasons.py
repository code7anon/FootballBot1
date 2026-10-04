import asyncio
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.db import SessionLocal
from backend.app.services.thesportsdb import TheSportsDBProvider

async def main():
    provider = TheSportsDBProvider(SessionLocal())
    season = os.getenv("BACKFILL_SEASON", "2024-2025")
    leagues = [x for x in os.getenv("BACKFILL_LEAGUES", "4328").split(",") if x]
    if not provider.enabled:
        raise SystemExit("THESPORTSDB_API_KEY is missing")
    for league in leagues:
        count = await provider.sync_season(league, season)
        print(f"league={league} season={season} fixtures={count}")

asyncio.run(main())