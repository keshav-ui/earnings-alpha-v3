# Earnings Alpha v3 — research and paper-trading platform

Earnings Alpha v3 is a **research and paper-trading** application for event-driven US equity earnings signals. It never submits broker orders: `ENABLE_LIVE_ORDERS` must remain `false` and the API has no live-order route.

## Strategy window

Entries are allowed after an earnings announcement in after-hours or pre-market. A paper position can be manually closed at any point until the next regular US market open. Configurable target/stop defaults are +5.5%/-3.5%; any remaining position is force-closed at the next regular-session open.

## Included

- Full responsive analysis dashboard with symbol input, session selection, configurable target/stop, factor explanation, trade plan, positions and manual **EXIT NOW**
- Persistent automatic watchlist that checks every 10 seconds, detects a newly published result, compares actual EPS/revenue with consensus, reads normalized guidance/commentary, and refreshes price/spread/volume analysis
- Provider adapter contracts for market data/order flow, earnings consensus, SEC/XBRL, and transcripts/news
- Deterministic replay/mock provider whenever credentials are absent
- Historical JSONL event ingestion and leakage-safe feature snapshots
- Event-driven backtest with bid/ask fills, spread, slippage and opening-gap handling
- Walk-forward evaluation, Platt probability calibration, threshold selection
- SQLAlchemy persistence compatible with SQLite locally and PostgreSQL in deployment
- Structured JSON logs, tests, Docker, Render Blueprint and GitHub Actions

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Open http://localhost:8000. The app seeds one replay event and runs only in paper/replay mode until authenticated provider credentials are supplied.

## API examples

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/events
curl -X POST http://localhost:8000/api/analyze \
  -H 'content-type: application/json' \
  -d '{"symbol":"NVDA","session":"after_market","target_pct":0.055,"stop_pct":0.035}'
curl -X POST http://localhost:8000/api/positions \
  -H 'content-type: application/json' \
  -d '{"event_id":1,"side":"LONG","quantity":10}'
curl -X POST http://localhost:8000/api/positions/1/exit -H 'content-type: application/json' -d '{"price":105.2}'
```

## Data providers and credentials

`MARKET_DATA_API_KEY`, `EARNINGS_API_KEY`, and `TRANSCRIPT_API_KEY` are optional. Their adapters deliberately raise a clear configuration error until an authenticated provider-specific implementation is completed. SEC data is public, but requests must include `SEC_USER_AGENT` (name/email) and obey SEC rate limits. No credentials are included or fabricated.

For licensed live monitoring, configure `MASSIVE_API_KEY` plus a normalized earnings gateway using `EARNINGS_RESULTS_URL` (include `{symbol}` in the URL) and `EARNINGS_API_KEY`. The result JSON must contain `actual_eps`, `estimated_eps`, `actual_revenue`, `estimated_revenue`, and `announced_at`; it may also contain `guidance_score`, `commentary`, and `source`. Optional transcript/news uses `TRANSCRIPT_NEWS_URL` and `TRANSCRIPT_API_KEY`. The dashboard reports every channel as LIVE or REPLAY and never labels fallback data as live.

The 10-second interval is an application polling target, not a guarantee that an upstream publisher or plan delivers within 10 seconds. Exchange market-data entitlements and earnings/news feed licensing determine actual latency.

The `ReplayProvider` is used automatically when an adapter cannot be authenticated. It is deterministic and suitable only for demonstrations/tests — it is not market data.

## Historical validation

Place events in `data/events.jsonl`; each line contains `event`, `bars`, and optionally `consensus`/`fundamentals`. Every bar needs `timestamp`, `bid`, `ask`, `last`, `volume`. Then run:

```bash
python -m earnings_alpha.validation --input data/events.jsonl --output reports/walk_forward.json
```

The validator builds features only from information timestamped at or before entry, fits calibration on earlier folds, selects a threshold on validation folds, and reports the untouched test folds. It cannot establish profitability from replay/sample data.

## Deploy to Render

1. Create an empty GitHub repository and upload this package's contents.
2. In Render choose **New → Blueprint**, select the repository, and approve `render.yaml`.
3. Create a managed PostgreSQL instance or allow the Blueprint to create it; Render supplies `DATABASE_URL`.
4. In the web service set a long `APP_SECRET`, `SEC_USER_AGENT`, and only credentials you have licensed. Keep `ENABLE_LIVE_ORDERS=false`.
5. Confirm `/health` returns `{"status":"ok","live_execution":false}` and run replay/paper validation before any future execution discussion.

No live deployment is claimed by this repository; deployment requires your authenticated GitHub/Render accounts and licensed provider access.
