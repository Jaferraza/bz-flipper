import time
from typing import Dict, Any, List, Optional
from app.cache import MarketCache
from app.db import Database
from app.models import BazaarItemState, MarketSnapshot
from app.profit import is_good_buy_suggestion


class DashboardService:
    """
    Business service executing search, filtering, sorting, lookback diffs,
    and history charts over already-computed in-memory cache and SQLite records.
    Never calls the upstream API.
    """

    def __init__(self, cache: MarketCache, db: Database):
        self.cache = cache
        self.db = db

    def get_market_data(
        self,
        search: Optional[str] = None,
        sort_by: str = "profit",
        sort_dir: str = "desc",
        min_profit: Optional[float] = None,
        min_volume: Optional[int] = None,
        budget_cap: Optional[float] = None,
        favorites: Optional[List[str]] = None,
        favorites_only: bool = False,
        lookback_window: str = "1h",  # 'last', '1h', '24h'
    ) -> Dict[str, Any]:
        snapshot = self.cache.get_snapshot()
        items = list(snapshot.items)

        # 1. Filter favorites
        fav_set = set(favorites or [])
        if favorites_only:
            items = [it for it in items if it.item_id in fav_set]

        # 2. Search query filter
        if search:
            query = search.strip().lower()
            items = [
                it
                for it in items
                if query in it.item_id.lower() or query in it.display_name.lower()
            ]

        # 3. Minimum profit, volume, budget thresholds
        if (
            min_profit is not None
            or min_volume is not None
            or budget_cap is not None
        ):
            items = [
                it
                for it in items
                if is_good_buy_suggestion(
                    it,
                    min_profit=min_profit,
                    min_volume=min_volume,
                    budget_cap=budget_cap,
                )
            ]

        # 4. Sorting
        reverse = sort_dir.lower() == "desc"

        def sort_key(it: BazaarItemState):
            if sort_by == "profit":
                val = it.profit_per_flip
                return (val is not None, val if val is not None else 0)
            elif sort_by == "roi":
                val = it.roi_percent
                return (val is not None, val if val is not None else 0)
            elif sort_by == "spread":
                val = it.spread
                return (val is not None, val if val is not None else 0)
            elif sort_by == "sell_price":
                val = it.sell_offer_price
                return (val is not None, val if val is not None else 0)
            elif sort_by == "buy_price":
                val = it.buy_order_price
                return (val is not None, val if val is not None else 0)
            elif sort_by == "volume":
                val = it.sell_volume
                return (val is not None, val if val is not None else 0)
            elif sort_by == "name":
                return (True, it.display_name.lower())
            elif sort_by == "profit_per_hour":
                val = it.profit_per_hour
                return (val is not None, val if val is not None else 0)
            else:
                val = it.profit_per_flip
                return (val is not None, val if val is not None else 0)

        items.sort(key=sort_key, reverse=reverse)

        # 5. Lookback boundary calculation for price/volume changes
        now = int(time.time())
        window_seconds_map = {
            "last": 600,
            "1h": 3600,
            "24h": 86400,
        }
        window_seconds = window_seconds_map.get(lookback_window, 3600)
        target_time = now - window_seconds

        serialized_items = []
        for it in items:
            item_dict = it.to_dict()
            item_dict["isFavorite"] = it.item_id in fav_set

            # Historical comparison diff
            prev_snapshot = self.db.get_snapshot_at_or_before(it.item_id, target_time)
            if prev_snapshot and prev_snapshot.get("sell_offer_price") is not None:
                prev_sell = prev_snapshot["sell_offer_price"]
                cur_sell = it.sell_offer_price
                if cur_sell is not None:
                    item_dict["priceChange"] = round(cur_sell - prev_sell, 2)
                    if prev_sell > 0:
                        item_dict["priceChangePercent"] = round(
                            ((cur_sell - prev_sell) / prev_sell) * 100, 2
                        )
                    else:
                        item_dict["priceChangePercent"] = None
                else:
                    item_dict["priceChange"] = None
                    item_dict["priceChangePercent"] = None

                prev_vol = prev_snapshot.get("sell_volume")
                cur_vol = it.sell_volume
                if prev_vol is not None and cur_vol is not None:
                    item_dict["volumeChange"] = cur_vol - prev_vol
                else:
                    item_dict["volumeChange"] = None
            else:
                item_dict["priceChange"] = None
                item_dict["priceChangePercent"] = None
                item_dict["volumeChange"] = None

            serialized_items.append(item_dict)

        return {
            "generatedAt": snapshot.generated_at,
            "lastRefreshAt": snapshot.last_refresh_at,
            "nextRefreshAt": snapshot.next_refresh_at,
            "stale": snapshot.stale,
            "refreshInProgress": snapshot.refresh_in_progress,
            "versionHash": snapshot.version_hash,
            "totalCount": len(serialized_items),
            "lookbackWindow": lookback_window,
            "items": serialized_items,
        }

    def get_item_detail(self, item_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves current cached item state + historical chart data points.
        """
        item = self.cache.get_item(item_id)
        if not item:
            # Check DB if not currently in cache
            latest = self.db.get_latest_snapshot(item_id)
            if not latest:
                return None

        # Fetch history (last 7 days)
        history_points = self.db.get_history(item_id, window_seconds=7 * 86400)

        item_dict = item.to_dict() if item else {}
        if not item_dict and latest:
            item_dict = {
                "itemId": latest["item_id"],
                "displayName": item_id,
                "buyOrderPrice": latest["buy_order_price"],
                "sellOfferPrice": latest["sell_offer_price"],
                "buyVolume": latest["buy_volume"],
                "sellVolume": latest["sell_volume"],
                "spread": latest["spread"],
                "taxAmount": latest["tax_amount"],
                "profitPerFlip": latest["profit_per_flip"],
                "roiPercent": latest["roi_percent"],
                "stale": True,
            }

        return {
            "item": item_dict,
            "history": [hp.to_dict() for hp in history_points],
            "disclaimer": (
                "Net profit = sell offer - buy order - 1% tax on sale proceeds. "
                "Profit/hour is unavailable until the API's volume time basis is confirmed."
            ),
        }

    def get_history_series(
        self, item_id: str, window: str = "24h"
    ) -> List[Dict[str, Any]]:
        window_seconds_map = {
            "last": 600,
            "1h": 3600,
            "24h": 86400,
            "7d": 7 * 86400,
        }
        window_seconds = window_seconds_map.get(window, 86400)
        points = self.db.get_history(item_id, window_seconds=window_seconds)
        return [hp.to_dict() for hp in points]
