from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Football Edge Bot"
    env: str = "development"
    log_level: str = "INFO"

    database_url: str | None = None
    postgresql_addon_uri: str | None = None

    # TheSportsDB (nadomešča API-Football)
    thesportsdb_api_key: str = "3"
    thesportsdb_base_url: str = "https://www.thesportsdb.com/api/v1/json"
    football_season: str = "2024-2025"
    tracked_leagues: str = "4328,4335,4331,4332,4334"

    odds_api_key: str | None = None
    odds_api_base_url: str = "https://api.the-odds-api.com/v4"
    odds_enabled: bool = False
    odds_sport_key: str = "soccer_epl"
    odds_regions: str = "eu"
    odds_markets: str = "h2h,totals"
    odds_bookmakers: str = ""

    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_enabled: bool = False

    paper_trading: bool = True
    initial_bankroll: float = 1000.0
    min_edge: float = 0.04
    max_stake_pct: float = 0.005
    kelly_fraction: float = 0.25
    max_daily_bets: int = 10
    max_open_exposure_pct: float = 0.03

    poll_seconds: int = 900
    max_live_fixtures: int = 20
    enrich_limit: int = 3
    odds_calls_per_day_cap: int = 10

    admin_token: str = "change-me"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    @property
    def league_ids(self) -> list[str]:
        return [x.strip() for x in self.tracked_leagues.split(",") if x.strip()]

    @property
    def cors(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    def resolved_database_url(self) -> str:
        value = self.database_url or self.postgresql_addon_uri
        if value:
            if value.startswith("postgres://"):
                value = value.replace("postgres://", "postgresql+psycopg://", 1)
            elif value.startswith("postgresql://"):
                value = value.replace("postgresql://", "postgresql+psycopg://", 1)
            return value
        return "sqlite:///./football_edge.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()