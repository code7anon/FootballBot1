# Deployment

## 1. Clever Cloud PostgreSQL

Create a PostgreSQL `DEV` add-on for testing. Copy its public PostgreSQL URI into Render as `DATABASE_URL`.

## 2. GitHub

Push this repository to GitHub. Keep `.env` and API keys out of the repository.

## 3. Render

Create a Web Service from the repository and use the included `render.yaml` / Dockerfile.

Required environment variables:

- `DATABASE_URL`
- `API_FOOTBALL_KEY`
- `ADMIN_TOKEN`

Optional:

- `ODDS_API_KEY`
- `ODDS_ENABLED=true`

Recommended first values:

- `TRACKED_LEAGUES=39`
- `FOOTBALL_SEASON=2026`
- `PAPER_TRADING=true`
- `MAX_STAKE_PCT=0.005`
- `MIN_EDGE=0.04`

## 4. Optional GitHub scheduler

Create GitHub repository secrets:

- `EDGE_API_URL` = your Render URL, e.g. `https://your-app.onrender.com`
- `EDGE_ADMIN_TOKEN` = same value as Render `ADMIN_TOKEN`

The workflow will hit `/api/admin/run-cycle` every 20 minutes.

## 5. Historical data

After deployment, run the backfill endpoint or local script for at least one completed season. Example:

```bash
BACKFILL_SEASON=2025 BACKFILL_LEAGUES=39 python scripts/backfill_seasons.py
```

For a remote Render deployment you can call:

```bash
curl -X POST "https://YOUR-APP.onrender.com/api/admin/backfill?league_id=39&season=2025" \
  -H "x-admin-token: YOUR_ADMIN_TOKEN"
```

## 6. First test

1. Open the dashboard.
2. Run one manual cycle.
3. Verify fixtures and predictions.
4. Enable odds only after the fixture data is correct.
5. Leave paper trading on.
