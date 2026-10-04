from __future__ import annotations
from datetime import datetime, date, timezone
from typing import Any
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..config import get_settings
from ..models import Team, Fixture, MatchSnapshot, InjurySnapshot

settings = get_settings()


class TheSportsDBProvider:
    """Provider za TheSportsDB API. Uporablja brezplačni ključ '3'."""

    # Mapiranje TheSportsDB ID-jev na naše kode lig
    LEAGUE_NAMES = {
        "4328": "Premier League",
        "4335": "La Liga",
        "4331": "Bundesliga",
        "4332": "Serie A",
        "4334": "Ligue 1",
    }

    def __init__(self, db: Session):
        self.db = db
        self.enabled = bool(settings.thesportsdb_api_key)

    async def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict:
        if not self.enabled:
            raise RuntimeError("THESPORTSDB_API_KEY is not configured")
        url = f"{settings.thesportsdb_base_url}/{settings.thesportsdb_api_key}/{endpoint}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, params=params or {})
            response.raise_for_status()
            return response.json()

    def _upsert_team(self, team_id: str, name: str, logo: str | None = None) -> Team:
        provider_id = int(team_id)
        team = self.db.scalar(select(Team).where(Team.provider_id == provider_id))
        if not team:
            team = Team(provider_id=provider_id, name=name)
            self.db.add(team)
        team.name = name
        if logo:
            team.logo = logo
        self.db.flush()
        return team

    def _map_status(self, status: str | None) -> str:
        if not status:
            return "NS"
        s = status.upper()
        if "FT" in s or "FINISHED" in s or "MATCH FINISHED" in s:
            return "FT"
        if "LIVE" in s or "HT" in s or "1H" in s or "2H" in s:
            return "LIVE"
        if "POSTP" in s:
            return "PST"
        if "CANC" in s:
            return "CANC"
        return "NS"

    def _safe_int(self, value) -> int | None:
        if value is None or value == "" or value == "null":
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def _upsert_fixture_from_event(self, event: dict) -> Fixture:
        event_id = int(event["idEvent"])
        league_id = self._safe_int(event.get("idLeague")) or 0
        home_team = self._upsert_team(
            event["idHomeTeam"], event["strHomeTeam"], event.get("strHomeTeamBadge")
        )
        away_team = self._upsert_team(
            event["idAwayTeam"], event["strAwayTeam"], event.get("strAwayTeamBadge")
        )
        # TheSportsDB format: "2024-10-05T18:30:00+00:00" ali "2024-10-05"
        kickoff = None
        if event.get("strTimestamp"):
            try:
                kickoff = datetime.fromisoformat(
                    event["strTimestamp"].replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except ValueError:
                pass
        if not kickoff and event.get("dateEvent"):
            try:
                kickoff = datetime.fromisoformat(event["dateEvent"])
            except ValueError:
                pass
        kickoff = kickoff or datetime.utcnow()

        fixture = self.db.scalar(select(Fixture).where(Fixture.provider_id == event_id))
        if not fixture:
            fixture = Fixture(
                provider_id=event_id,
                league_id=league_id,
                season=int(settings.football_season.split("-")[0]),
                kickoff=kickoff,
                status=self._map_status(event.get("strStatus")),
                home_team_id=home_team.id,
                away_team_id=away_team.id,
            )
            self.db.add(fixture)
        fixture.league_id = league_id
        fixture.kickoff = kickoff
        fixture.status = self._map_status(event.get("strStatus"))
        fixture.home_team_id = home_team.id
        fixture.away_team_id = away_team.id
        fixture.home_goals = self._safe_int(event.get("intHomeScore"))
        fixture.away_goals = self._safe_int(event.get("intAwayScore"))
        fixture.raw_json = event
        fixture.last_synced_at = datetime.utcnow()
        self.db.flush()
        return fixture

    async def sync_day(self, day: date) -> int:
        """Prenese vse tekme za določen dan iz izbranih lig."""
        total = 0
        data = await self._get("eventsday.php", {"d": day.isoformat(), "s": "Soccer"})
        events = data.get("events") or []
        for event in events:
            if not event.get("idEvent"):
                continue
            # Filtriraj samo lige, ki jih spremljamo
            league_id = str(event.get("idLeague") or "")
            if league_id not in settings.league_ids:
                continue
            self._upsert_fixture_from_event(event)
            total += 1
        self.db.commit()
        return total

    async def sync_season(self, league_id: str, season: str | None = None) -> int:
        """Prenese celotno sezono za določeno ligo."""
        season = season or settings.football_season
        data = await self._get("eventsseason.php", {"id": league_id, "s": season})
        events = data.get("events") or []
        total = 0
        for event in events:
            if not event.get("idEvent"):
                continue
            self._upsert_fixture_from_event(event)
            total += 1
        self.db.commit()
        return total

    async def sync_live(self) -> int:
        """Prenese tekme v živo."""
        if not self.enabled:
            return 0
        try:
            data = await self._get("livescore.php", {"s": "Soccer"})
        except Exception:
            return 0
        events = data.get("events") or []
        count = 0
        for event in events:
            if not event.get("idEvent"):
                continue
            league_id = str(event.get("idLeague") or "")
            if league_id not in settings.league_ids:
                continue
            fixture = self._upsert_fixture_from_event(event)
            await self._capture_live_snapshot(fixture, event)
            count += 1
            if count >= settings.max_live_fixtures:
                break
        self.db.commit()
        return count

    async def _capture_live_snapshot(self, fixture: Fixture, event: dict) -> None:
        """Shrani statistiko tekme v živo (če je na voljo)."""
        self.db.add(MatchSnapshot(
            fixture_id=fixture.id,
            raw_json=event,
        ))

    async def enrich_fixture_injuries(self, fixture_id: int) -> int:
        """TheSportsDB brezplačni paket ne ponuja podatkov o poškodbah. Vrne 0."""
        return 0

    async def injuries(self, team_provider_id: int) -> list[dict]:
        """Ni na voljo v brezplačnem paketu."""
        return []