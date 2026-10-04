from __future__ import annotations
from datetime import datetime, timezone, date
import httpx
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from ..config import get_settings
from ..models import OddsSnapshot, Fixture, SystemState, Team

settings = get_settings()


class OddsProvider:
    def __init__(self, db: Session):
        self.db = db
        self.enabled = settings.odds_enabled and bool(settings.odds_api_key)

    async def _get(self, path: str, params: dict) -> tuple[dict | list, dict[str, str]]:
        if not self.enabled:
            raise RuntimeError("Odds API disabled or missing key")
        params = {**params, "apiKey": settings.odds_api_key}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{settings.odds_api_base_url}{path}", params=params)
            response.raise_for_status()
            return response.json(), dict(response.headers)

    def _usage_key(self) -> str:
        return f"odds_usage:{datetime.now(timezone.utc).date().isoformat()}"

    def usage_today(self) -> int:
        state = self.db.get(SystemState, self._usage_key())
        return int((state.value_json if state else {}).get("calls", 0))

    def _inc_usage(self, amount: int = 1):
        key = self._usage_key()
        state = self.db.get(SystemState, key)
        if not state:
            state = SystemState(key=key, value_json={"calls": 0})
            self.db.add(state)
            self.db.flush()
        state.value_json = {"calls": self.usage_today() + amount}
        self.db.flush()

    async def sync_odds(self) -> int:
        if not self.enabled:
            return 0
        if self.usage_today() >= settings.odds_calls_per_day_cap:
            return 0
        payload, headers = await self._get(f"/sports/{settings.odds_sport_key}/odds", {
            "regions": settings.odds_regions,
            "markets": settings.odds_markets,
            "oddsFormat": "decimal",
            **({"bookmakers": settings.odds_bookmakers} if settings.odds_bookmakers else {}),
        })
        self._inc_usage(1)
        count = 0
        for event in payload if isinstance(payload, list) else []:
            home = str(event.get("home_team", "")).strip()
            away = str(event.get("away_team", "")).strip()
            kickoff = event.get("commence_time")
            fixture = self._match_fixture(home, away, kickoff)
            for bookmaker in event.get("bookmakers", []):
                for market in bookmaker.get("markets", []):
                    for outcome in market.get("outcomes", []):
                        self.db.add(OddsSnapshot(
                            fixture_provider_id=fixture.provider_id if fixture else None,
                            event_provider_id=event.get("id"),
                            bookmaker=bookmaker.get("key") or bookmaker.get("title") or "unknown",
                            market=market.get("key") or "unknown",
                            selection=outcome.get("name") or "unknown",
                            line=outcome.get("point"),
                            odds=float(outcome.get("price")),
                            raw_json={"event": event, "bookmaker": bookmaker, "market": market, "headers": {
                                "remaining": headers.get("x-requests-remaining"),
                                "used": headers.get("x-requests-used"),
                            }},
                        ))
                        count += 1
        self.db.commit()
        return count

    def _match_fixture(self, home: str, away: str, kickoff: str | None):
        fixtures = self.db.scalars(select(Fixture).order_by(Fixture.kickoff.desc()).limit(250)).all()
        def norm(s):
            return "".join(c.lower() for c in s if c.isalnum())
        h, a = norm(home), norm(away)
        best = None
        best_score = 0
        for f in fixtures:
            th = self.db.get(Team, f.home_team_id)
            ta = self.db.get(Team, f.away_team_id)
            if not th or not ta:
                continue
            score = 0
            if h in norm(th.name) or norm(th.name) in h: score += 1
            if a in norm(ta.name) or norm(ta.name) in a: score += 1
            if score > best_score:
                best_score = score
                best = f
        return best if best_score == 2 else None
