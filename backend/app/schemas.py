from datetime import datetime
from pydantic import BaseModel, ConfigDict


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    provider_id: int
    league_id: int
    kickoff: datetime
    status: str
    minute: int | None
    home_team: str
    away_team: str
    home_goals: int | None
    away_goals: int | None


class BetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    status: str
    market: str
    selection: str
    odds: float
    model_probability: float
    edge: float
    stake: float
    pnl: float | None

