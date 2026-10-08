# CraftersMC SkyBlock Bazaar API Notes

## Base URL
- **Production Base URL**: `https://api.craftersmc.net`

## Documented Endpoints (Authoritative)
1. **GET `/v1/resources/skyblock/bazaar/items`**
   - Returns a JSON array of valid Bazaar item ID strings (e.g. `["ENCHANTED_DIAMOND", "SUPER_COMPACTOR_3000"]`).
   - Does not provide human-readable display names; names are derived in presentation layer.

2. **GET `/v1/skyblock/bazaar/{itemId}/details`**
   - Returns a `BazaarItemReply` JSON object:
     - `success` (boolean): must be validated.
     - `itemId` (string): item identifier.
     - `buyTopEntries` (array of `TopEntry`): `[{ price, quantity, orderCount }]`.
     - `sellTopEntries` (array of `TopEntry`): `[{ price, quantity, orderCount }]`.
     - `buyVolume` (integer): volume metric.
     - `sellVolume` (integer): volume metric.
     - `weeklyAveragePrice` (float): weekly average benchmark.

## Documented Status & Error Responses
- `400`: Invalid item ID or bad request parameter.
- `403`: Missing required API scope or key invalid.
- `404`: Bazaar data not populated yet for item.
- `429`: Upstream rate limit exceeded (handled with exponential backoff and Retry-After).
- `503`: Service temporarily unavailable.

## Architectural Constraints & Implementation Decisions
- **No Documented Bulk Endpoint**: The API does not expose a single bulk details endpoint. The application performs a bounded concurrent fan-out across item IDs during each 10-minute refresh cycle.
- **Frontend Isolation**: Frontend clients never query CraftersMC directly. All dashboard requests are answered from local in-memory cache and SQLite history.
- **Order-Book Best Price Selection**:
  - Highest buy bid: `MAX(buyTopEntries[].price)`
  - Lowest sell ask: `MIN(sellTopEntries[].price)`
  - Do not assume index 0 is pre-sorted.
- **Tax Interpretation**: 1% (`0.01`) tax modeled on sell proceeds: `profit_per_flip = sell_offer_price * 0.99 - buy_order_price`.
- **Volume Semantics & Profit/Hour**: Because `buyVolume` and `sellVolume` do not specify a time window or traded vs order-book depth, `profit_per_hour` is null/unavailable by default and marked heuristic if enabled.
