# BZ Flip – Session Summary

## 1. Core Objectives & User Requests

| # | Request | Status |
|---|---------|--------|
| 1 | `/caveman on` — terse mode activated | ✅ Done |
| 2 | Explain what you did (re: initial implementation) | ✅ Done |
| 3 | How to run the app | ✅ Done |
| 4 | Why only 7 items tracked? | ✅ Answered (concurrency limit + rate limit) |
| 5 | Stress test for rate limit value | ✅ Done — found 40 req / 5 min hard limit |
| 6 | Priority rotation: favorites selectable from website, bumped to front of queue; request every 7.5s; whole bazaar accounted for | 🟡 Mostly done — 1 test failing |

---

## 2. Key Decisions & Conclusions

### Rate Limiting
- CraftersMC enforces a **hard limit of ~40 requests per 5 minutes**
- First 39 concurrent requests succeeded; remaining 246 hit `429`
- **Resolution**: Sequential pacing at **`UPSTREAM_REQUEST_DELAY_SECONDS = 7.5`** — gives ~8 req/min (480/hr), safely under limit
- 429 errors cause the item to be **re-inserted at the front of the queue** with a backoff sleep

### Auth Header
- Initial attempt used `Authorization: Bearer <key>` → `401`
- Correct header: **`X-API-Key: <key>`** → `200`
- Config key: `CRAFTERSMC_API_KEY_HEADER=X-API-Key`

### Architecture Constraints (hard rules)
- Frontend clients **never** query CraftersMC directly
- All dashboard requests served from **local in-memory cache + SQLite history**
- The API has **no bulk details endpoint** — app does bounded concurrent fan-out

---

## 3. Technical Details & Architecture

### Stack
```
Flask (Python)
├── app/
│   ├── api_client.py      # CraftersMCClient (X-API-Key auth)
│   ├── bazaar_adapter.py  # derive_display_name(), metrics calc
│   ├── cache.py           # In-memory cache, upsert_item, queueProgress
│   ├── config.py          # Config dataclass incl. UPSTREAM_REQUEST_DELAY_SECONDS
│   ├── db.py              # SQLite: item_history + favorites tables
│   ├── models.py          # BazaarItemState dataclass
│   ├── refresher.py       # BazaarRefresher — sequential queue, priority bump
│   ├── routes.py          # Flask Blueprint: /api/market, /api/status, etc.
│   ├── services.py        # DashboardService
│   └── static/app.js      # Frontend: catalog autocomplete, favorites toggle, queue poller
│   └── templates/index.html
tests/
├── test_routes.py         # 23 tests — 1 FAILING
└── test_refresher.py      # Priority queue tests
```

### Refresher Queue Logic (`app/refresher.py`)
```python
# Sequential pacing — one request every 7.5s
UPSTREAM_REQUEST_DELAY_SECONDS = 7.5

# Priority bump: favorites go to front
def bump_favorite(self, item_id: str):
    with self._queue_lock:
        if item_id in self._active_queue:
            self._active_queue.remove(item_id)
        self._active_queue.insert(0, item_id)

# 429 handling: re-insert at front + sleep
except RateLimitExceededError:
    with self._queue_lock:
        self._active_queue.insert(0, item_id)
    time.sleep(backoff)
```

### SQLite Schema Additions (`app/db.py`)
```sql
CREATE TABLE IF NOT EXISTS favorites (
    item_id TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);
```

### New API Endpoints (`app/routes.py`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/status` | Cache + refresher health, queue progress |
| GET | `/api/items/catalog` | Full bazaar item list with display names |
| GET | `/api/favorites` | Retrieve favorited item IDs from SQLite |
| POST | `/api/favorites` | Set/toggle favorite; bumps item in queue |

### POST `/api/favorites` Payload
```json
// Single item
{ "itemId": "ENCHANTED_DIAMOND", "isFavorite": true }

// Bulk replace
{ "favorites": ["ENCHANTED_DIAMOND", "ENCHANTED_IRON"] }
```

### Frontend Additions (`app/static/app.js`)
- **Catalog autocomplete**: `<datalist>` populated from `/api/items/catalog`
- **Favorites toggle**: star button per row → POST to `/api/favorites`
- **Queue progress poller**: polls `/api/status` every 5s, shows chip with `X/285 refreshed`

---

## 4. Unresolved Tasks & Open Questions

### 🔴 Failing Test
**`test_api_status_and_refresh`** in [`tests/test_routes.py`](file:///c:/Users/jafskf/bz%20flip/tests/test_routes.py#L149-L161) — specifically line 159:
```python
res_refresh = client.post("/api/refresh")
assert res_refresh.status_code == 200  # FAILS with 404
```

**Root cause**: The `/api/refresh` route is **missing** from [`app/routes.py`](file:///c:/Users/jafskf/bz%20flip/app/routes.py). It was accidentally dropped when the file was replaced to add favorites/catalog endpoints.

**Fix needed** — add back to `routes.py`:
```python
@bp.route("/api/refresh", methods=["POST"])
def trigger_refresh():
    """Manually triggers a refresh cycle (non-blocking)."""
    refresher = get_refresher()
    triggered = refresher.trigger()
    return jsonify({"status": "triggered" if triggered else "already_running"})
```

### 🟡 Catalog Endpoint Test
`test_api_favorites_and_catalog` depends on `refresher.get_catalog_items()` returning items — verify this method exists and is wired to the mock correctly.

### Open Questions
- Should favorites persist across server restarts? (Currently yes — SQLite)
- Should the catalog be pre-populated from a static list or only from live API data?
- Is the 7.5s delay acceptable for full 285-item cycle time (~35 minutes per full pass)?

---

## 5. Instructions & Constraints for Fresh Continuation

### Environment Setup
```bash
cd "c:/Users/jafskf/bz flip"
pip install -r requirements.txt
python run.py          # dev server
pytest                 # run tests
```

### `.env` Keys Required
```
CRAFTERSMC_API_KEY=<your key>
CRAFTERSMC_API_KEY_HEADER=X-API-Key
UPSTREAM_REQUEST_DELAY_SECONDS=7.5
DB_PATH=data/bazaar.db
```

### Hard Constraints
1. **No direct upstream calls from frontend** — cache only
2. **Auth header is `X-API-Key`** (not `Authorization: Bearer`)
3. **Rate limit: 40 req / 5 min** — never fan-out concurrently
4. **7.5s between requests** is the safe pacing cadence
5. **Favorites are SQLite-persisted** and bumped to front of `_active_queue`
6. `BazaarRefresher` uses `_queue_lock` (threading.Lock) — always acquire before mutating `_active_queue`

### Immediate Next Action
Add the missing `/api/refresh` POST route to [`app/routes.py`](file:///c:/Users/jafskf/bz%20flip/app/routes.py) (see code snippet above). Then run `pytest` — should go from 22/23 to 23/23 passing.
