# Football Edge Bot — free-first MVP

A research/paper-betting platform for football. It collects fixtures, optional odds and match data, builds a baseline + ML probability model, calculates edge, simulates stakes with conservative risk limits, and exposes a dashboard.

> This repository is deliberately **paper-trading first**. No real-money bookmaker integration is enabled. The live execution layer is an adapter interface that can later be connected to an officially supported bookmaker/exchange API after you verify the provider's API terms and local legal requirements.

## Architecture

- `backend/` — FastAPI API, PostgreSQL/SQLite persistence, data providers, model, edge and paper-betting engine.
- `frontend/` — React + Vite dashboard.
- `scripts/` — local utilities for demo data and scheduled cycles.
- `.github/workflows/poller.yml` — optional scheduled HTTP poller to keep the free Render deployment active without a paid worker.

## Free-first deployment

### Render

Deploy the backend as a Render Web Service. The React app is built into `backend/app/static` during the Render build so one service serves both API and dashboard.

Render free web services are suitable for testing but sleep after 15 minutes without inbound traffic and have ephemeral filesystems. This app therefore stores persistent data only in PostgreSQL and can be pinged periodically by the optional GitHub Actions workflow.

### Clever Cloud PostgreSQL

Create a PostgreSQL DEV plan and set `DATABASE_URL` to the supplied URI. If you link the add-on to a Clever Cloud app, Clever Cloud exposes PostgreSQL environment variables; this project accepts either `DATABASE_URL` or the standard `POSTGRESQL_ADDON_*` variables.

## Providers

### API-Football

Set `API_FOOTBALL_KEY`. The app uses `https://v3.football.api-sports.io` and the `x-apisports-key` header. The free plan currently has 100 requests/day, so the collector is intentionally conservative and batches detailed fixture reads.

### The Odds API

Set `ODDS_API_KEY` to enable odds ingestion. The free tier currently has 500 credits/month. By default the system only queries one configured sport key per cycle to avoid wasting credits. Set `ODDS_SPORT_KEY=soccer_epl` for the first MVP.

## Local run

```bash
cp .env.example .env
# put keys into .env if available

python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate

pip install -r backend/requirements.txt

cd frontend
npm install
npm run build
cd ..

# copy frontend/dist -> backend/app/static happens automatically with scripts/build_frontend.sh on Unix,
# or run the equivalent copy manually on Windows.

uvicorn backend.app.main:app --reload
```

Open http://127.0.0.1:8000

For a no-key demo:

```bash
python scripts/generate_demo_data.py
```

## Environment

See `.env.example`.

## Important model notes

This MVP uses an interpretable ensemble:

1. Elo-style team strength
2. Poisson goal baseline
3. Logistic/gradient-boosting ML when enough completed matches exist
4. Market comparison -> implied probability -> edge -> conservative fractional-Kelly-inspired stake

The model does **not** claim guaranteed profit. The dashboard tracks ROI, drawdown, CLV-style reference fields, calibration, edge and result distributions.

## Suggested first deployment configuration

Start with:

- `TRACKED_LEAGUES=39` (Premier League only)
- `ODDS_SPORT_KEY=soccer_epl`
- `ODDS_ENABLED=true` only when you have the key
- `PAPER_TRADING=true`
- `MAX_STAKE_PCT=0.005`
- `MIN_EDGE=0.04`
- `MAX_DAILY_BETS=10`
- `POLL_SECONDS=900`

Once the data quality and backtests are convincing, add more competitions and more markets.


## Free mode vs true live mode

The free-first setup is a scheduled collector, not a tick-by-tick trading engine. GitHub Actions calls the Render endpoint every 20 minutes; the API-Football free plan has 100 requests/day and The Odds API free plan has 500 credits/month. For true in-play monitoring at roughly the provider update cadence, move `backend/worker_main.py` to a paid Render Background Worker and tune `POLL_SECONDS`.
