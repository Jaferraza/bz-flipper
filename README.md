# CraftersMC Bazaar Flip Dashboard

A lightweight, high-performance local dashboard that queries CraftersMC SkyBlock Bazaar data from `https://api.craftersmc.net`, refreshes and caches it every 10 minutes, persists price snapshots in SQLite with change-detection deduplication, and highlights lucrative flipping opportunities.

Built with Python (Flask), SQLite, Vanilla JavaScript, and minimal modern CSS. No frontend build tools, bundlers, or external package managers required.

---

## Key Features

- **10-Minute Snapshot Cache**: Background worker cycle runs every 600 seconds (`CACHE_TTL_SECONDS=600`).
- **Complete Route Isolation**: Frontend/dashboard queries are served 100% from in-memory cache and SQLite. Upstream is never called in response to user requests.
- **Order-Book Arbitrage Metrics**:
  - Highest buy order price (`MAX(buyTopEntries[].price)`)
  - Lowest sell offer price (`MIN(sellTopEntries[].price)`)
  - Configurable 1% tax on sell proceeds (`BAZAAR_TAX_RATE = 0.01`)
  - Net Profit, ROI (%), Gross Spread, and conservative quantity/budget calculation.
- **SQLite History & Deduplication**:
  - Automatically records historical snapshots when price or volume values change.
  - Automatically prunes snapshot history older than 7 days on startup and refresh.
  - Recent change lookback diffs (since last refresh, 1 hour, 24 hours).
- **Interactive Single-Page Interface**:
  - Dark / Light mode (with automatic `prefers-color-scheme` support and manual toggle).
  - Search, sort, min profit, min volume, and budget cap filters.
  - Watchlist / Favorites saved in browser `localStorage`.
  - Item detail inspection modal with 7-day price history chart using vendored Chart.js.
  - Responsive desktop table and mobile stacked cards (<= 640px).
  - Background polling pauses when browser tab is hidden and resumes on focus.

---

## Quickstart

### 1. Requirements
- Python 3.10+ (tested on Python 3.14)

### 2. Setup Virtual Environment & Install Dependencies
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure Environment
```bash
cp .env.example .env
```
*(The API key is optional during development; test fixtures or real API key can be inserted into `.env`).*

### 4. Run the Dashboard
```bash
python run.py
```
Open your browser at:
**[http://127.0.0.1:5000](http://127.0.0.1:5000)**

---

## Configuration Reference

All settings can be customized via `.env`:

| Variable | Default | Description |
|---|---|---|
| `CRAFTERSMC_API_BASE_URL` | `https://api.craftersmc.net` | Authoritative CraftersMC API base URL |
| `CRAFTERSMC_API_KEY` | `""` | Optional API token injected via isolated client |
| `HOST` | `127.0.0.1` | Localhost binding only |
| `PORT` | `5000` | Local web port |
| `CACHE_TTL_SECONDS` | `600` | Refresh cadence (10 minutes) |
| `STATIC_METADATA_TTL_SECONDS` | `43200` | Item IDs list cache TTL (12 hours) |
| `BAZAAR_TAX_RATE` | `0.01` | Bazaar sales tax rate (1%) |
| `UPSTREAM_MAX_CONCURRENCY` | `4` | Concurrency ceiling for per-item details fetch |
| `UPSTREAM_TIMEOUT_SECONDS` | `15` | Upstream request timeout |
| `UPSTREAM_MAX_RETRIES` | `3` | Max retries with backoff and jitter |
| `SNAPSHOT_RETENTION_DAYS` | `7` | SQLite snapshot retention window |
| `USE_MOCK_API` | `false` | Enable to use local schema-faithful JSON fixtures |

---

## Testing

Run the full pytest suite:
```bash
pytest -v
```

The test suite includes 22 unit and integration tests covering:
- Best bid/ask order book price selection
- Tax, spread, net profit, ROI, and budget calculations
- Null guards and divide-by-zero prevention
- State hash generation and snapshot deduplication
- 7-day snapshot retention pruning
- 429 rate limit backoff and dynamic concurrency reduction
- Cache ETag generation and HTTP 304 conditional responses
- Assertion of zero upstream calls during route handling
