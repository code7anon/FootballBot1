from __future__ import annotations
from datetime import datetime, date, timezone
from typing import Any
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..config import get_settings
from ..models import Team, Fixture, MatchSnapshot, InjurySnapshot

settings = get_settings()


class FootballProvider:
    def __init__(self, db: Session):
        self.db = db
        self.enabled = bool(settings.api_football_key)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        if not self.enabled:
            raise RuntimeError("API_FOOTBALL_KEY is not configured")
        headers = {"x-apisports-key": settings.api_football_key}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(f"{settings.api_football_base_url}{path}", params=params or {}, headers=headers)
            response.raise_for_status()
            data = response.json()
            if data.get("errors"):
                raise RuntimeError(str(data["errors"]))
            return data

    def _upsert_team(self, item: dict) -> Team:
        provider_id = int(item["id"])
        team = self.db.scalar(select(Team).where(Team.provider_id == provider_id))
        if not team:
            team = Team(provider_id=provider_id, name=item.get("name", str(provider_id)))
            self.db.add(team)
        team.name = item.get("name", team.name)
        team.logo = item.get("logo")
        self.db.flush()
        return team

    def _upsert_fixture(self, item: dict) -> Fixture:
        f = item["fixture"]
        teams = item["teams"]
        goals = item.get("goals") or {}
        league = item.get("league") or {}
        home = self._upsert_team(teams["home"])
        away = self._upsert_team(teams["away"])
        kickoff = datetime.fromtimestamp(f["timestamp"], tz=timezone.utc).replace(tzinfo=None)
        fixture = self.db.scalar(select(Fixture).where(Fixture.provider_id == int(f["id"])))
        if not fixture:
            fixture = Fixture(
                provider_id=int(f["id"]),
                league_id=int(league.get("id") or 0),
                season=int(league.get("season") or settings.football_season),
                kickoff=kickoff,
                status=(f.get("status") or {}).get("short") or "NS",
                home_team_id=home.id,
                away_team_id=away.id,
            )
            self.db.add(fixture)
        fixture.league_id = int(league.get("id") or fixture.league_id)
        fixture.season = int(league.get("season") or fixture.season)
        fixture.kickoff = kickoff
        fixture.status = (f.get("status") or {}).get("short") or fixture.status
        fixture.minute = (f.get("status") or {}).get("elapsed")
        fixture.home_team_id = home.id
        fixture.away_team_id = away.id
        fixture.home_goals = goals.get("home")
        fixture.away_goals = goals.get("away")
        fixture.raw_json = item
        fixture.last_synced_at = datetime.utcnow()
        self.db.flush()
        return fixture

    async def sync_day(self, day: date) -> int:
        total = 0
        for league_id in settings.leagues_ids:
            data = await self._get("/fixtures", {
                "league": league_id,
                "season": settings.football_season,
                "date": day.isoformat(),
                "timezone": "UTC",
            })
            for item in data.get("response", []):
                self._upsert_fixture(item)
                total += 1
        self.db.commit()
        return total

    async def sync_season(self, league_id: int, season: int) -> int:
        data = await self._get("/fixtures", {"league": league_id, "season": season})
        total = 0
        for item in data.get("response", []):
            self._upsert_fixture(item)
            total += 1
        self.db.commit()
        return total

    async def enrich_fixture_injuries(self, fixture_id: int) -> int:
        fixture = self.db.scalar(select(Fixture).where(Fixture.id == fixture_id))
        if not fixture:
            return 0
        total = 0
        for team_provider_id in [
            self.db.get(Team, fixture.home_team_id).provider_id,
            self.db.get(Team, fixture.away_team_id).provider_id,
        ]:
            items = await self.injuries(team_provider_id, fixture.provider_id)
            key_out = 0
            severity = 0.0
            for row in items:
                player = row.get("player") or {}
                # Heuristic only; do not pretend the API provides an injury severity score.
                reason = str(row.get("player", {}).get("type") or row.get("player", {}).get("reason") or "").lower()
                key_out += 1 if any(k in reason for k in ["injury", "susp", "out"]) else 0
                severity += 1.0
            self.db.add(InjurySnapshot(fixture_id=fixture.id, team_provider_id=team_provider_id, player_count=len(items), key_players_out=key_out, severity_score=severity, raw_json=items))
            total += 1
        self.db.commit()
        return total

    async def sync_live(self) -> int:
        if not self.enabled:
            return 0
        ids_param = "-".join(str(x) for x in settings.leagues_ids)
        data = await self._get("/fixtures", {"live": ids_param})
        count = 0
        for item in data.get("response", [])[: settings.max_live_fixtures]:
            fixture = self._upsert_fixture(item)
            await self.capture_fixture_details(fixture.provider_id, item)
            count += 1
        self.db.commit()
        return count

    async def capture_fixture_details(self, fixture_id: int, embedded: dict | None = None) -> dict | None:
        item = embedded
        if item is None:
            data = await self._get("/fixtures", {"id": fixture_id})
            item = (data.get("response") or [None])[0]
            if not item:
                return None
        fixture = self._upsert_fixture(item)
        stats = item.get("statistics") or []
        # Store only normalized team totals when present.
        values: dict[int, dict[str, Any]] = {}
        for team_block in stats:
            team_id = int((team_block.get("team") or {}).get("id") or 0)
            values[team_id] = {str(s.get("type")): s.get("value") for s in team_block.get("statistics", [])}

        def num(team_id: int, key: str):
            v = values.get(team_id, {}).get(key)
            if isinstance(v, str):
                v = v.replace("%", "")
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        snap = MatchSnapshot(
            fixture_id=fixture.id,
            home_shots=num(fixture.home_team_id, "Total Shots"),
            away_shots=num(fixture.away_team_id, "Total Shots"),
            home_sot=num(fixture.home_team_id, "Shots on Goal"),
            away_sot=num(fixture.away_team_id, "Shots on Goal"),
            home_possession=num(fixture.home_team_id, "Ball Possession"),
            away_possession=num(fixture.away_team_id, "Ball Possession"),
            home_corners=num(fixture.home_team_id, "Corner Kicks"),
            away_corners=num(fixture.away_team_id, "Corner Kicks"),
            home_xg=num(fixture.home_team_id, "Expected Goals"),
            away_xg=num(fixture.away_team_id, "Expected Goals"),
            raw_json=stats,
        )
        self.db.add(snap)
        self.db.flush()
        return item

    async def team_form(self, team_provider_id: int, last: int = 5) -> list[dict]:
        data = await self._get("/fixtures", {"team": team_provider_id, "last": last, "status": "FT-AET-PEN"})
        return data.get("response", [])

    async def injuries(self, team_provider_id: int, fixture_id: int | None = None) -> list[dict]:
        params = {"team": team_provider_id, "season": settings.football_season}
        if fixture_id:
            params["fixture"] = fixture_id
        data = await self._get("/injuries", params)
        return data.get("response", [])
