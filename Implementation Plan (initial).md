Task: Implementation plan for a CraftersMC Bazaar Flip Dashboard

Goal

Create a localhost web page that pulls CraftersMC SkyBlock Bazaar data from https://api.craftersmc.net, refreshes and caches it every 10 minutes, persists price changes for history, and shows which items are worth buying and reselling.

This task is PLAN ONLY. Do not implement the application yet. The implementation plan produced from this prompt must be detailed enough that a later implementation phase can proceed without rediscovering the architecture or data model.

Repository requirement

Create a fresh Git repository for this project as part of the work. There is no existing application repository to preserve.

Use a simple Python web backend with Flask, vanilla JavaScript, one small CSS file, and SQLite. Do not introduce a frontend framework, bundler, transpiler, package manager, or JavaScript build step.

Keep the project runnable locally on 127.0.0.1 only.

Authoritative API source

The supplied CraftersMC OpenAPI specification is authoritative for documented endpoint paths and upstream response field names. The supplied HTML export is a saved copy of the live API documentation page at https://api.craftersmc.net/docs and may be used as supporting documentation, but it does not override the OpenAPI schema.

The API base URL is fixed as:
https://api.craftersmc.net

Authentication

An API credential will be supplied later. Never hard-code it.

Store it in a local .env file, loaded by the backend at startup. Include .env in .gitignore. Provide a .env.example showing the variable names but no real secret.

The precise authentication header/format is not specified yet, so isolate credential injection in the API client. Do not invent a header name or bearer format in the plan. The plan must explicitly identify this as an open integration detail to be filled in when the credential instructions arrive.

Rate limits

CraftersMC does not define a numeric request-per-minute or request-per-second rate limit in the supplied specification. The API documents HTTP 429 for rate-limit exceeded responses.

Do not invent a numeric official limit. Design the refresher so concurrency and backoff are configurable and can be tuned empirically from observed 429 responses and refresh duration.

Suggested safe default for the first implementation pass: low bounded concurrency for item-detail requests (for example 4 workers), with the value configurable and easy to reduce to 1 if the upstream begins returning 429. This is a local implementation default, not a claimed CraftersMC rate limit.

Supplied OpenAPI facts that must be used

The relevant documented Bazaar endpoints are:

GET /v1/resources/skyblock/bazaar/items
- Returns the list of available Bazaar item IDs.

GET /v1/skyblock/bazaar/{itemId}/details
- Returns Bazaar details for one item.
- BazaarItemReply contains:
  - success
  - itemId
  - buyTopEntries[]
  - sellTopEntries[]
  - buyVolume
  - sellVolume
  - weeklyAveragePrice
- TopEntry contains:
  - price
  - quantity
  - orderCount

The Bazaar-item details endpoint documents these error responses:
400 invalid item ID, 403 missing required API scope, 404 data not populated yet, 429 rate limit exceeded, and 503 service temporarily unavailable.

The OpenAPI specification does not define a bulk Bazaar-details endpoint.

Important consequence for refresh architecture

Do NOT retain the original requirement that one refresh must consist of exactly one upstream HTTP request, because the supplied API does not provide a documented bulk Bazaar endpoint.

Instead define one logical background refresh cycle owned by one refresher. A cycle should:
1. Use the cached item-ID list.
2. Issue one details request per Bazaar item, with bounded configurable concurrency.
3. Optionally refresh the item-ID list on a much longer schedule such as 12 hours or at startup.
4. Publish the newest successfully fetched item states into the in-memory cache.
5. Never perform upstream API calls in response to frontend/user requests.

This is the required solution to the documented API shape.

If the item count and measured request duration make a full cycle unable to complete comfortably within 10 minutes, the plan must call this out as a capacity risk and recommend reducing concurrency only when 429s occur, otherwise increasing concurrency within safe observed limits. Never hide the issue by silently skipping items without marking them stale.

Refresh and cache requirement

Bazaar data must be refreshed and cached every 10 minutes (600 seconds).

CACHE_TTL_SECONDS = 600 is the default and required normal operating interval.

Do not invent a shorter freshness claim. The dashboard must clearly communicate that the data is a cached snapshot refreshed every 10 minutes.

The background refresher is the only component allowed to access CraftersMC. Every frontend/API request is served from the local in-memory cache and/or SQLite history. No user request may call the upstream API.

On startup:
- load configuration;
- initialize SQLite;
- load cached metadata and the latest known Bazaar state if persisted state is available;
- start the background refresher;
- perform an initial refresh immediately so the dashboard can populate as soon as possible.

Refresh behavior:
- Normal schedule: every 600 seconds.
- Never overlap refresh cycles.
- Coalesce concurrent refresh triggers behind a single refresh lock/state machine.
- Use a bounded thread pool or equivalent low-concurrency mechanism for the per-item details calls.
- Successful item responses replace the corresponding cached item state.
- Failed item responses retain the last good value for that item and mark the item stale/error as appropriate.
- A refresh failure must never replace valid cached values with nulls or zeros merely because the upstream request failed.
- The API response field `success` must be validated before accepting a response as data.

Upstream conditional requests

The OpenAPI specification does not document ETag or Last-Modified behavior for Bazaar responses.

Implement support opportunistically in the HTTP client:
- if an upstream response supplies ETag, retain it and send If-None-Match on subsequent requests when applicable;
- if an upstream response supplies Last-Modified, retain it and send If-Modified-Since on subsequent requests when applicable;
- handle 304 as not modified.

Do not make correctness depend on these headers being available.

Change detection

Because the Bazaar schema does not expose a Bazaar-specific last-updated timestamp, record a local fetch timestamp for every accepted item response and every published refresh snapshot.

Also compute a stable hash of the normalized Bazaar state (or a per-item hash) after mapping the upstream payload into the internal domain model.

Use the hashes to determine whether data actually changed between refreshes. This is for observability and snapshot minimization, not as a replacement for the fixed 10-minute refresh schedule.

Persistence

Use SQLite for historical price data.

Retention:
- Keep 7 days of price snapshots.
- Prune old rows on a scheduled basis and also safely on startup.

Storage minimization:
- Store a row for an item only when its mapped historical state changes from the previous stored state.
- At minimum, the historical state used for change detection should include buy-order price, sell-offer price, buy volume, and sell volume.
- Do not create a fake row every 10 minutes when nothing changed.

Index snapshots by item ID and timestamp.

Favorites are never stored in SQLite. Favorites use browser localStorage only.

API field mapping

Use the supplied upstream field names exactly in the API client and centralize mapping in one adapter/module.

Required mapping for the dashboard:

item_id
- Upstream source: BazaarItemReply.itemId.
- Type: string.

buy_order_price
- Upstream data source: BazaarItemReply.buyTopEntries[].price.
- Semantic target: highest current buy-order price (the best bid).
- Preferred implementation rule: take the maximum price among the returned buyTopEntries rather than blindly assuming array index 0 is ordered best-first.
- Open question: confirm that buyTopEntries represents buy orders and that the returned entries are valid current order-book levels. The endpoint names strongly suggest this, but the OpenAPI prose does not explicitly define array ordering or execution semantics.

sell_offer_price
- Upstream data source: BazaarItemReply.sellTopEntries[].price.
- Semantic target: lowest current sell-offer price (the best ask).
- Preferred implementation rule: take the minimum price among the returned sellTopEntries rather than blindly assuming array index 0 is ordered best-first.
- Open question: confirm that sellTopEntries represents sell offers and that the returned entries are valid current order-book levels. The OpenAPI prose does not explicitly define array ordering or execution semantics.

buy_volume
- Upstream source: BazaarItemReply.buyVolume.
- Type: integer.
- Important: the specification does not define whether this is active order-book depth, executed volume, a rolling-window quantity, or another measure. Do not label it as hourly traded volume without confirmation.

sell_volume
- Upstream source: BazaarItemReply.sellVolume.
- Type: integer.
- Same semantic limitation as buy_volume.

weekly_average_price
- Upstream source: BazaarItemReply.weeklyAveragePrice.
- Not required for the primary flip calculation but may be retained for future analysis or context.

display_name
- The documented item-list endpoint returns item IDs only; it does not document human-readable item names.
- Therefore the plan must not invent a separate upstream name field.
- V1 fallback: derive a readable label from item_id for display only (for example convert underscores to spaces and apply basic capitalization), while retaining item_id as the authoritative identifier.
- Isolate this presentation mapping so a future trusted metadata source can replace it without changing the Bazaar adapter.

Profit calculation

Bazaar tax rate:
BAZAAR_TAX_RATE = 0.01 (1%).

Treat the 1% tax as a configurable rate, not a hard-coded constant, so it can be changed later if CraftersMC confirms a different rule.

Required formulas:

Gross spread:
spread = sell_offer_price - buy_order_price

Tax amount:
tax = sell_offer_price * BAZAAR_TAX_RATE

Net profit per flip:
profit_per_flip = (sell_offer_price - buy_order_price) - tax

Equivalent expanded form:
profit_per_flip = sell_offer_price * (1 - BAZAAR_TAX_RATE) - buy_order_price

ROI:
roi_percent = profit_per_flip / buy_order_price * 100

Guard against divide-by-zero and missing prices. If either side of the book is unavailable, profit/ROI should be null rather than misleadingly shown as zero.

Use decimal-safe arithmetic in the backend for monetary calculations rather than relying on binary floating-point behavior. Store/serialize according to the precision accepted by the API and format for display separately.

Tax interpretation open point

The supplied information gives a 1% tax rate but does not explicitly state the tax base or rounding rule. The implementation plan should use tax on sell-offer proceeds as the current working interpretation, because the profit definition subtracts bazaar tax from the sale side, but it must flag tax-base/rounding as a confirmation item before treating the result as authoritative.

Profit/hour

The API specification does not define the time window or semantics of buyVolume/sellVolume. Therefore the project must not pretend that these fields are an actual hourly trade rate.

Define the metric in the domain model as:
profit_per_hour = profit_per_flip * estimated_flips_per_hour

For the current API, estimated_flips_per_hour must be marked heuristic unless CraftersMC confirms that volume fields represent traded quantity over a known window.

Preferred authoritative formula once volume semantics are confirmed:
estimated_flips_per_hour = MIN(buyVolume, sellVolume) / volume_window_hours
profit_per_hour = profit_per_flip * estimated_flips_per_hour

Until volume_window_hours and the meaning of buyVolume/sellVolume are confirmed, expose profit_per_hour as unavailable/null in the API and UI, sort nulls last, and explain the limitation in the item detail view.

Do not fabricate an hourly conversion factor.

If a heuristic profit/hour is desired for early testing, make it explicitly opt-in and configurable, for example:
heuristic_flips_per_hour = MIN(buyVolume, sellVolume) / HEURISTIC_VOLUME_WINDOW_HOURS
with HEURISTIC_VOLUME_WINDOW_HOURS defaulting to 1.0 only as a temporary model assumption. Label it HEURISTIC everywhere it appears. Do not use the heuristic in the default ranked recommendations unless explicitly enabled.

Flip ranking

The default flip-suggestion ranking should primarily use positive net profit per flip, then use ROI and volume as secondary tie-breakers.

Exclude an item from good-buy suggestions when:
- buy-order price is missing;
- sell-offer price is missing;
- spread/profit is non-positive;
- the item fails user-configured minimum volume/profit thresholds;
- the item exceeds the optional budget cap when the cap is enabled.

Make ranking deterministic so the same cache snapshot and filter settings always produce the same ordering.

Budget cap behavior

Interpret the optional budget cap as the maximum total purchase cost for the candidate flip quantity.

For V1, because the API does not define executable quantity across both sides, use a conservative candidate quantity of:
quantity = MIN(best_buy_quantity, best_sell_quantity)
where best_buy_quantity is the quantity attached to the selected highest buy-order price and best_sell_quantity is the quantity attached to the selected lowest sell-offer price.

Then enforce:
required_budget = buy_order_price * quantity

Flag this as an order-book-depth assumption because the schema documents quantities but does not explicitly state whether all returned quantities are immediately fillable by a single trader.

Recent changes

Provide selectable windows:
- since last accepted refresh;
- 1 hour;
- 24 hours.

Price change should compare the current mapped price against the latest historical snapshot at or before the requested lookback boundary, with clearly documented boundary behavior.

Volume change should compare the current buy/sell volume values against the corresponding historical values when those fields are semantically comparable. Because the volume time basis is undocumented, label volume changes as order-book/value changes until CraftersMC documents their exact semantics.

If there is no historical snapshot before the requested boundary, return null/not available instead of estimating.

Item detail view

Clicking an item row opens a detail view containing:
- display name and item ID;
- current buy-order price;
- current sell-offer price;
- spread;
- tax rate and tax amount;
- net profit per flip;
- ROI;
- buy volume and sell volume;
- last successful fetch time;
- stale status if applicable;
- price history chart.

Chart.js is allowed. Do not add a build step; load the library through a normal browser-compatible mechanism or a locally vendored static file, keeping the dependency choice simple.

The detail view must include a concise explanation such as:
"Net profit = sell offer - buy order - 1% tax on sale proceeds. Profit/hour is unavailable until the API's volume time basis is confirmed."

Backend architecture

Use a small Flask application with clear separation of concerns.

Recommended logical modules:
- app/bootstrap/config: configuration and startup;
- api_client: CraftersMC HTTP calls, authentication injection, retries, conditional headers, response validation;
- bazaar_adapter: upstream field mapping and order-book interpretation;
- domain/profit: tax, spread, profit, ROI, optional profit/hour model;
- cache/refresher: in-memory current-state cache and 10-minute refresh lifecycle;
- persistence/db: SQLite schema, snapshot writes, historical reads, pruning;
- service/dashboard: query/filter/sort operations over already-computed cached state;
- routes: HTTP endpoints and response headers;
- static frontend: vanilla JS and one CSS file.

The critical rule is that no route handler calls the CraftersMC API directly.

Repository tree

The fresh repository should follow this shape unless a concrete implementation reason requires an equivalent simple adjustment:

craftersmc-bazaar-flip-dashboard/
  .env.example
  .gitignore
  README.md
  requirements.txt
  run.py
  app/
    __init__.py
    config.py
    routes.py
    models.py
    api_client.py
    bazaar_adapter.py
    profit.py
    cache.py
    refresher.py
    db.py
    services.py
    templates/
      index.html
    static/
      app.js
      styles.css
  fixtures/
    bazaar-items.mock.json
    bazaar-item-details.mock.json
  tests/
    test_profit.py
    test_bazaar_adapter.py
    test_cache.py
    test_refresher.py
    test_routes.py
  data/
    .gitkeep
  docs/
    IMPLEMENTATION_PLAN.md
    API_NOTES.md

Do not add node_modules, package-lock.json, webpack/vite configuration, React/Vue/Svelte files, or a frontend build directory.

Backend endpoints

The application API should expose only local dashboard endpoints. Suggested endpoints:

GET /
- Renders the dashboard shell.

GET /api/market
- Returns the current cached Bazaar rows, with derived metrics already computed.
- Supports query parameters for search, sort, minimum volume, minimum profit, budget cap, and favorites-only view if useful, but filtering/sorting must operate on cached data only.

Example payload shape:
{
  "generatedAt": "2026-10-08T19:30:00+03:00",
  "lastRefreshAt": "2026-10-08T19:30:00+03:00",
  "nextRefreshAt": "2026-10-08T19:40:00+03:00",
  "stale": false,
  "items": [
    {
      "itemId": "MOCK_ITEM",
      "displayName": "Mock Item",
      "buyOrderPrice": 100.0,
      "sellOfferPrice": 120.0,
      "spread": 20.0,
      "taxAmount": 1.2,
      "profitPerFlip": 18.8,
      "roiPercent": 18.8,
      "buyVolume": 1000,
      "sellVolume": 900,
      "profitPerHour": null,
      "lastUpdated": "2026-10-08T19:30:00+03:00",
      "stale": false
    }
  ]
}

GET /api/items/{item_id}
- Returns the current cached state plus historical points needed for the chart.
- Never fetches the upstream endpoint on demand.

GET /api/history/{item_id}?window=24h
- Returns stored historical snapshot points for the requested window.

GET /api/status
- Returns cache/refresher health information, including last successful refresh, stale age, refresh-in-progress state, and the number of items successfully refreshed versus retained from prior cache.

HTTP caching

For local API responses whose contents derive from the same cache snapshot:
- generate an application ETag from the published cache version/hash;
- return Cache-Control appropriate for 10-minute polling;
- honor If-None-Match and return 304 when the snapshot has not changed.

Do not let browser caching bypass the stale-data indicator logic.

SQLite schema

Design a minimal schema similar to:

items
- item_id TEXT PRIMARY KEY
- display_name TEXT NOT NULL
- created_at INTEGER/ISO timestamp
- updated_at INTEGER/ISO timestamp

price_snapshots
- id INTEGER PRIMARY KEY
- item_id TEXT NOT NULL
- captured_at INTEGER NOT NULL
- buy_order_price NUMERIC NULL
- sell_offer_price NUMERIC NULL
- buy_volume INTEGER NULL
- sell_volume INTEGER NULL
- spread NUMERIC NULL
- tax_amount NUMERIC NULL
- profit_per_flip NUMERIC NULL
- roi_percent NUMERIC NULL
- state_hash TEXT NOT NULL
- FOREIGN KEY(item_id) REFERENCES items(item_id)

Create indexes:
- price_snapshots(item_id, captured_at)
- price_snapshots(captured_at)

Only persist a new snapshot row when the mapped historical state changes from the previous stored state for that item. Derived fields may be stored for convenient historical/chart retrieval, but the source-of-truth price/volume values must remain present.

Retention pruning should delete rows older than 7 days.

Configuration

Use environment variables loaded from .env. Provide safe development defaults where appropriate.

Required/important configuration values:
- CRAFTERSMC_API_BASE_URL=https://api.craftersmc.net
- CRAFTERSMC_API_KEY=<provided later>
- CACHE_TTL_SECONDS=600
- STATIC_METADATA_TTL_SECONDS=43200
- BAZAAR_TAX_RATE=0.01
- DB_PATH=./data/bazaar.db
- SNAPSHOT_RETENTION_DAYS=7
- UPSTREAM_MAX_CONCURRENCY=4
- UPSTREAM_TIMEOUT_SECONDS=15
- UPSTREAM_MAX_RETRIES=3
- REFRESH_JITTER_SECONDS=0
- ENABLE_HEURISTIC_PROFIT_PER_HOUR=false
- HEURISTIC_VOLUME_WINDOW_HOURS=1.0

Do not claim that the suggested concurrency, timeout, or retry values are CraftersMC requirements. They are implementation defaults and must be configurable.

Error handling and backoff

Handle at minimum:
- network timeout/connectivity failures;
- HTTP 400 for invalid item IDs;
- HTTP 403 authentication/scope failures;
- HTTP 404 when Bazaar data is not populated;
- HTTP 429 rate limiting;
- HTTP 503 service unavailable.

On 429:
- do not immediately hammer the endpoint with retries;
- apply exponential backoff with jitter;
- respect Retry-After when present;
- reduce effective concurrency for subsequent refresh cycles if repeated 429s occur;
- retain the last good per-item data;
- surface stale/error state to the dashboard.

Because CraftersMC provides no numeric official rate limit, do not implement a made-up hard quota. Use observed responses and configurable concurrency/backoff.

On an individual item failure during a mostly successful refresh, retain the prior item state and mark that item stale. A partial refresh should not make healthy cached items unavailable.

On total refresh failure, preserve the complete last good cache and show a global stale indicator with the age of the last successful refresh.

Concurrency and coalescing

Only one refresher instance should own the refresh lifecycle.

Within a refresh cycle, multiple item requests may run concurrently subject to UPSTREAM_MAX_CONCURRENCY.

Frontend requests must never trigger a second simultaneous refresh. A manual refresh control, if included, should only request a local refresh signal that is coalesced by the existing refresher lock and should not allow users to bypass the 10-minute protection through repeated clicks.

Frontend behavior

Use vanilla JavaScript.

Initial page load:
- fetch local cached dashboard data;
- render immediately even if the cache is stale;
- display stale state prominently but without blocking interaction.

Polling:
- poll the local backend every 600 seconds;
- pause polling when document.hidden is true;
- resume with one local cache fetch when the tab becomes visible again;
- do not call CraftersMC directly from JavaScript.

Searching, filtering, sorting, and favorites should all operate locally from the cached market payload unless there is a strong reason to request a new local filtered payload.

Responsive layout:
- desktop: table;
- narrow screens around 640px and below: stacked cards;
- sticky search/sort/filter bar;
- comfortable touch targets;
- minimal animation;
- accessible labels and keyboard navigation.

Use system light/dark mode via prefers-color-scheme.

Favorites/watchlist

Store favorites in localStorage using item IDs as the stable key.

Provide:
- star toggle in rows/cards;
- Favorites section or favorites-only filter;
- persistence across reloads;
- no alerts or notifications.

Mock fixtures

Use schema-faithful fixtures based on the supplied OpenAPI schema, not invented fields.

At minimum include:
- a Bazaar item list fixture containing several string item IDs;
- a Bazaar item-details fixture containing success, itemId, buyTopEntries, sellTopEntries, buyVolume, sellVolume, and weeklyAveragePrice;
- enough variation to test profitable, unprofitable, missing-order-book-side, and changed-volume scenarios.

For the order book tests, include more than one TopEntry on each side so the adapter test proves that it selects the maximum buy price and minimum sell price rather than blindly assuming index 0.

Test approach

Unit tests:
- buy-order price selection from multiple buyTopEntries;
- sell-offer price selection from multiple sellTopEntries;
- spread calculation;
- 1% tax calculation;
- net profit calculation;
- ROI calculation;
- null handling for missing prices and zero buy price;
- budget cap calculation using conservative matched quantity;
- state hashing/change detection;
- snapshot deduplication when nothing changed;
- 1-hour and 24-hour history lookback behavior;
- cache hit behavior so routes never invoke the upstream client;
- ETag generation and 304 behavior;
- stale cache preservation after timeout/429/503;
- refresher concurrency coalescing;
- Retry-After/exponential-backoff behavior;
- partial refresh behavior where one item fails but other items succeed.

Integration tests:
- start the Flask app against the mock client/fixtures;
- populate cache;
- call local API endpoints repeatedly;
- verify no upstream request occurs after cache population except when the background refresher runs;
- verify SQLite history and pruning behavior.

No test should require a live CraftersMC API key.

Acceptance criteria

The implementation plan must make it possible to verify that:

1. The app runs only on 127.0.0.1.
2. CraftersMC calls are isolated in the API client/refresher layer.
3. The API base URL is https://api.craftersmc.net.
4. The API credential is read from .env and is never hard-coded.
5. Bazaar data refreshes on a 600-second normal cadence.
6. Frontend requests never call CraftersMC directly.
7. Derived profit/ROI/ranking values are computed once per accepted refresh, not repeatedly per route request.
8. Buy-order price is selected as the highest buyTopEntries[].price.
9. Sell-offer price is selected as the lowest sellTopEntries[].price.
10. Net profit uses a configurable 1% tax rate, currently interpreted as tax on sell proceeds.
11. Profit/hour is null/unavailable by default until the volume time semantics are confirmed; any heuristic is explicitly opt-in and labeled.
12. SQLite retains up to 7 days of changed snapshots and prunes older data.
13. The UI can show current data, 1h change, 24h change, search, sorting, thresholds, budget cap, detail view, chart, and favorites.
14. The browser pauses polling while hidden.
15. API responses use ETag/Cache-Control and support 304 for unchanged cache snapshots.
16. Failures preserve the last good data and display the age/stale state.
17. Repeated 429s do not cause retry storms.
18. There is no route-level upstream fetch.
19. The repository contains tests for profit logic, adapter mapping, cache behavior, and refresher failure handling.

Risks

The plan must explicitly discuss these risks:

- The lack of a documented bulk Bazaar endpoint means a full refresh requires one item-details HTTP request per Bazaar item.
- The lack of a numeric upstream rate limit makes the safe concurrency ceiling an empirical setting rather than a documented value.
- The lack of a Bazaar freshness timestamp means local fetch time is the only guaranteed freshness indicator.
- buyTopEntries/sellTopEntries ordering and exact order-book semantics are not fully specified.
- buyVolume/sellVolume semantics and time basis are not specified, so profit/hour cannot be authoritative yet.
- Human-readable item names are not provided by the documented item-list endpoint.
- The 1% tax rate is supplied externally, but tax base and rounding semantics are still not formally documented.
- A strict 10-minute cadence is a cache policy, not a guarantee that prices themselves change every 10 minutes.
- Partial refreshes can temporarily mix fresh and stale item states and must be surfaced clearly.
- Large item counts may make a full refresh take close to or longer than 10 minutes.

Open questions / confirmations required before implementation

1. What exact authentication header and credential format should be used for the API key?
2. What do buyTopEntries and sellTopEntries represent operationally, and are they guaranteed to be ordered best-first?
3. Are buyVolume and sellVolume active order-book quantities or traded quantities? What time window do they represent?
4. Can the API expose any undocumented bulk Bazaar endpoint that returns all item details in one response? If yes, document it before implementation; otherwise use the per-item fan-out described above.
5. Is the 1% tax applied to sell proceeds, and what rounding rule does the server/game use?
6. Are item IDs also the intended human-readable names, or is there a trusted item metadata source available?
7. Are ETag and/or Last-Modified supported by the live Bazaar endpoints?
8. Does the service provide Retry-After on 429 responses?
9. Approximately how many Bazaar items are currently returned by the item-list endpoint, and how long does one full refresh take with a small concurrency value?

Explicit assumptions

List these assumptions prominently in the implementation plan and distinguish them from documented facts:

- Local refresh/cache interval is exactly 600 seconds.
- API base URL is https://api.craftersmc.net.
- API key is supplied later and kept in .env.
- No official numeric rate limit is available; bounded concurrency and backoff are implementation controls, not claimed limits.
- buy order price is the maximum price in buyTopEntries[].price.
- sell offer price is the minimum price in sellTopEntries[].price.
- 1% tax is currently modeled as tax on sell proceeds.
- Profit/hour is unavailable by default until volume semantics are documented.
- V1 display names are derived from item IDs unless a trusted metadata source is supplied.
- Best executable flip quantity is conservatively approximated from the quantities attached to the selected best buy and sell price levels.
- Local timestamps are used for freshness because the Bazaar response schema has no documented lastUpdated/fetchedAt field.
- ETag/Last-Modified support is optional and opportunistic.

Non-goals

Do not add:
- authentication for dashboard users;
- accounts or multi-user state;
- price alerts;
- automated trading or order placement;
- production deployment tooling;
- cloud infrastructure;
- data sources other than CraftersMC;
- frontend build tooling;
- a second backend framework.
