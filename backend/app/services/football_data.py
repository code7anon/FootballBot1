from __future__ import annotations
from datetime import datetime, date, timezone
from typing import Any
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..config import get_settings
from ..models import Team, Fixture

settings = get_settings()


class FootballDataProvider:
    """Provider za Football-Data.org API v4."""

    def __init__(self, db: Session):
        self.db = db
        self.enabled = bool(settings.football_data_api_key)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        if not self.enabled:
            raise RuntimeError("FOOTBALL_DATA_API_KEY is not configured")
        headers = {"X-Auth-Token": settings.football_data_api_key}
        url = f"{settings.football_data_base_url}{path}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, params=params or {}, headers=headers)
            response.raise_for_status()
            return response.json()

    def _map_status(self, status: str | None) -> str:
        if not status:
            return "NS"
        s = status.upper()
        if s in {"FINISHED", "AWARDED"}:
            return "FT"
        if s in {"IN_PLAY", "PAUSED", "LIVE"}:
            return "LIVE"
        if s in {"POSTPONED", "SUSPENDED"}:
            return "PST"
        if s == "CANCELLED":
            return "CANC"
        return "NS"

    def _upsert_team(self, data: dict) -> Team:
        provider_id = int(data["id"])
        team = self.db.scalar(select(Team).where(Team.provider_id == provider_id))
        if not team:
            team = Team(provider_id=provider_id, name=data.get("name", str(provider_id)))
            self.db.add(team)
        team.name = data.get("name") or team.name
        team.logo = data.get("crest")
        self.db.flush()
        return team

    def _upsert_fixture(self, match: dict) -> Fixture:
        match_id = int(match["id"])
        competition = match.get("competition") or {}
        league_id = int(competition.get("id") or 0)

        home = self._upsert_team(match["homeTeam"])
        away = self._upsert_team(match["awayTeam"])

        kickoff = None
        if match.get("utcDate"):
            try:
                kickoff = datetime.fromisoformat(
                    match["utcDate"].replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except ValueError:
                pass
        kickoff = kickoff or datetime.utcnow()

        score = match.get("score") or {}
        full_time = score.get("fullTime") or {}

        fixture = self.db.scalar(select(Fixture).where(Fixture.provider_id == match_id))
        if not fixture:
            fixture = Fixture(
                provider_id=match_id,
                league_id=league_id,
                season=settings.football_season,
                kickoff=kickoff,
                status=self._map_status(match.get("status")),
                home_team_id=home.id,
                away_team_id=away.id,
            )
            self.db.add(fixture)
        fixture.league_id = league_id
        fixture.kickoff = kickoff
        fixture.status = self._map_status(match.get("status"))
        fixture.home_team_id = home.id
        fixture.away_team_id = away.id
        fixture.home_goals = full_time.get("home")
        fixture.away_goals = full_time.get("away")
        fixture.raw_json = match
        fixture.last_synced_at = datetime.utcnow()
        self.db.flush()
        return fixture

    async def sync_day(self, day: date) -> int:
        """Prenese vse tekme za določen dan iz vseh spremljanih lig."""
        data = await self._get("/matches", {
            "dateFrom": day.isoformat(),
            "dateTo": day.isoformat(),
        })
        total = 0
        for match in data.get("matches", []):
            self._upsert_fixture(match)
            total += 1
        self.db.commit()
        return total

    async def sync_season(self, competition_code: str, season: int | None = None) -> int:
        season = season or settings.football_season
        data = await self._get(
            f"/competitions/{competition_code}/matches",
            {"season": season},
        )
        total = 0
        for match in data.get("matches", []):
            self._upsert_fixture(match)
            total += 1
        self.db.commit()
        return total

    async def sync_live(self) -> int:
        # Football-Data.org brezplačni paket nima live endpointa.
        return 0

    async def enrich_fixture_injuries(self, fixture_id: int) -> int:
        # Ni na voljo v brezplačnem paketu.
        return 0