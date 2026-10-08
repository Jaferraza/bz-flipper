import hashlib
import json
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from app.models import BazaarItemState, MarketSnapshot
from app.profit import rank_items


class MarketCache:
    """
    Thread-safe in-memory cache holding current Bazaar market state.
    Pre-computes derived metrics, ranking, and version ETag on publish.
    """

    def __init__(self, ttl_seconds: int = 600):
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()

        now = datetime.now(timezone.utc)
        self.generated_at: str = now.isoformat()
        self.last_refresh_at: Optional[str] = None
        self.next_refresh_at: str = (now + timedelta(seconds=ttl_seconds)).isoformat()
        self.stale: bool = True  # Starts stale until first successful refresh
        self.refresh_in_progress: bool = False
        self.total_refresh_cycles: int = 0
        self.successful_refresh_cycles: int = 0
        self.failed_refresh_cycles: int = 0

        self._items: Dict[str, BazaarItemState] = {}
        self._ranked_items: List[BazaarItemState] = []
        self._version_hash: str = "initial"
        self.queue_progress = {"completed": 0, "total": 0, "currentItem": ""}

    def set_queue_progress(self, completed: int, total: int, current_item: str = "") -> None:
        with self._lock:
            self.queue_progress = {
                "completed": completed,
                "total": total,
                "currentItem": current_item,
            }

    def upsert_item(self, item: BazaarItemState) -> None:
        """
        Updates single item incrementally and immediately re-indexes ranking.
        """
        with self._lock:
            self._items[item.item_id] = item
            all_items = list(self._items.values())
            self._ranked_items = rank_items(all_items)
            now = datetime.now(timezone.utc)
            self.generated_at = now.isoformat()
            self.last_refresh_at = now.isoformat()
            self.stale = False

            hash_builder = hashlib.sha256()
            hash_builder.update(f"{self.last_refresh_at}:{len(all_items)}".encode("utf-8"))
            for it in self._ranked_items:
                hash_builder.update(f"{it.item_id}:{it.state_hash}:{it.stale}".encode("utf-8"))
            self._version_hash = hash_builder.hexdigest()[:16]

    def set_refresh_in_progress(self, in_progress: bool) -> None:
        with self._lock:
            self.refresh_in_progress = in_progress

    def publish_cycle_results(
        self,
        new_items: Dict[str, BazaarItemState],
        refresh_succeeded: bool,
        failed_item_ids: Optional[List[str]] = None,
    ) -> None:
        """
        Publishes the results of a background refresh cycle.
        - Successful item responses replace cached items.
        - Failed items retain their previous good state and are marked stale.
        - Never replaces valid cached values with nulls/zeros on failure.
        - Pre-computes ranking and ETag.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            self.generated_at = now.isoformat()
            self.total_refresh_cycles += 1
            self.refresh_in_progress = False

            if refresh_succeeded:
                self.successful_refresh_cycles += 1
                self.last_refresh_at = now.isoformat()
                self.next_refresh_at = (
                    now + timedelta(seconds=self.ttl_seconds)
                ).isoformat()
                self.stale = False
            else:
                self.failed_refresh_cycles += 1
                self.stale = True

            # Merge new items into cache
            for item_id, item_state in new_items.items():
                self._items[item_id] = item_state

            # Mark any specifically failed items as stale while preserving prior data
            if failed_item_ids:
                for fid in failed_item_ids:
                    if fid in self._items:
                        # Retain last good values, mark stale flag
                        self._items[fid].stale = True

            # Pre-compute deterministic ranking
            all_items = list(self._items.values())
            self._ranked_items = rank_items(all_items)

            # Compute stable version hash for ETag
            hash_builder = hashlib.sha256()
            hash_builder.update(f"{self.last_refresh_at}:{len(all_items)}".encode("utf-8"))
            for item in self._ranked_items:
                hash_builder.update(f"{item.item_id}:{item.state_hash}:{item.stale}".encode("utf-8"))
            self._version_hash = hash_builder.hexdigest()[:16]

    def warm_from_db(self, db_rows: List[Dict[str, Any]]) -> None:
        """
        Initializes cache from stored DB records on application startup.
        """
        with self._lock:
            if not db_rows:
                return
            for row in db_rows:
                item_id = row["item_id"]
                item = BazaarItemState(
                    item_id=item_id,
                    display_name=row.get("display_name", item_id),
                    buy_order_price=row.get("buy_order_price"),
                    sell_offer_price=row.get("sell_offer_price"),
                    buy_volume=row.get("buy_volume"),
                    sell_volume=row.get("sell_volume"),
                    spread=row.get("spread"),
                    tax_amount=row.get("tax_amount"),
                    profit_per_flip=row.get("profit_per_flip"),
                    roi_percent=row.get("roi_percent"),
                    state_hash=row.get("state_hash", ""),
                    last_updated=datetime.fromtimestamp(
                        row["captured_at"], timezone.utc
                    ).isoformat(),
                    stale=True,  # Initially marked stale until live refresh runs
                )
                self._items[item_id] = item

            all_items = list(self._items.values())
            self._ranked_items = rank_items(all_items)
            self._version_hash = f"warm-{len(all_items)}"

    def get_snapshot(self) -> MarketSnapshot:
        with self._lock:
            return MarketSnapshot(
                generated_at=self.generated_at,
                last_refresh_at=self.last_refresh_at or "",
                next_refresh_at=self.next_refresh_at,
                stale=self.stale,
                refresh_in_progress=self.refresh_in_progress,
                version_hash=self._version_hash,
                items=list(self._ranked_items),
            )

    def get_item(self, item_id: str) -> Optional[BazaarItemState]:
        with self._lock:
            return self._items.get(item_id)

    def get_items_with_timestamps(self) -> Dict[str, str]:
        """
        Returns a mapping of item_id -> last_updated ISO string for all cached
        items.  Used by the catalog endpoint and the priority queue sorter.
        """
        with self._lock:
            return {item_id: item.last_updated for item_id, item in self._items.items()}

    def get_status_info(self) -> Dict[str, Any]:
        with self._lock:
            items_list = list(self._items.values())
            stale_count = sum(1 for it in items_list if it.stale)
            active_count = len(items_list) - stale_count
            return {
                "generatedAt": self.generated_at,
                "lastRefreshAt": self.last_refresh_at,
                "nextRefreshAt": self.next_refresh_at,
                "stale": self.stale,
                "refreshInProgress": self.refresh_in_progress,
                "versionHash": self._version_hash,
                "totalItems": len(items_list),
                "activeItems": active_count,
                "staleItems": stale_count,
                "queueProgress": self.queue_progress,
                "totalCycles": self.total_refresh_cycles,
                "successfulCycles": self.successful_refresh_cycles,
                "failedCycles": self.failed_refresh_cycles,
            }
