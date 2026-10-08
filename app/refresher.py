import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Any, Set

from app.api_client import CraftersMCClient, UpstreamAPIError, RateLimitExceededError
from app.bazaar_adapter import adapt_bazaar_item
from app.cache import MarketCache
from app.config import Config
from app.db import Database
from app.models import BazaarItemState

logger = logging.getLogger(__name__)


class BazaarRefresher:
    """
    Background refresher owning the Bazaar data refresh lifecycle.
    Features:
    - Paced 7.5s requests to strictly adhere to CraftersMC 40 req/5min rate limit.
    - Priority queue: favorited items are placed/bumped at the front of the queue.
    - Incremental cache publishing so items appear live as they are fetched.
    - Automatic sleep and retry when upstream rate limit (429) occurs.
    """

    def __init__(
        self,
        config: Config,
        cache: MarketCache,
        db: Database,
        api_client: Optional[CraftersMCClient] = None,
    ):
        self.config = config
        self.cache = cache
        self.db = db
        self.api_client = api_client or CraftersMCClient(
            base_url=config.CRAFTERSMC_API_BASE_URL,
            api_key=config.CRAFTERSMC_API_KEY,
            api_key_header=config.CRAFTERSMC_API_KEY_HEADER,
            timeout_seconds=config.UPSTREAM_TIMEOUT_SECONDS,
            max_retries=config.UPSTREAM_MAX_RETRIES,
        )

        self.effective_concurrency = config.UPSTREAM_MAX_CONCURRENCY
        self._refresh_lock = threading.Lock()
        self._queue_lock = threading.Lock()
        self._cycle_running = False

        self._cached_item_ids: List[str] = []
        self._last_item_ids_fetch: float = 0.0

        self._active_queue: List[str] = []
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

    def start(self, initial_refresh: bool = True) -> None:
        """
        Starts the background refresher daemon thread.
        """
        if self._worker_thread and self._worker_thread.is_alive():
            return

        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._run_loop,
            args=(initial_refresh,),
            name="BazaarRefresherThread",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("Bazaar background refresher started")

    def stop(self, timeout: float = 5.0) -> None:
        """
        Signals background thread to stop.
        """
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=timeout)
            logger.info("Bazaar background refresher stopped")

    def trigger_manual_refresh(self) -> bool:
        """
        Trigger an immediate refresh cycle in background if not already running.
        """
        if self._cycle_running:
            return False

        threading.Thread(
            target=self.execute_refresh_cycle,
            name="ManualRefreshTrigger",
            daemon=True,
        ).start()
        return True

    def bump_favorite(self, item_id: str) -> None:
        """
        Bumps a newly favorited item to the front of the active refresh queue.
        """
        with self._queue_lock:
            if item_id in self._active_queue:
                self._active_queue.remove(item_id)
            self._active_queue.insert(0, item_id)
            logger.info("Bumped favorite item %s to the front of refresher queue", item_id)

    def _run_loop(self, run_initial: bool) -> None:
        if run_initial:
            self.execute_refresh_cycle()

        while not self._stop_event.is_set():
            # Wait for next cycle interval (e.g. 600s)
            interval = self.config.CACHE_TTL_SECONDS
            if self._stop_event.wait(timeout=interval):
                break
            self.execute_refresh_cycle()

    def get_catalog_items(self) -> List[str]:
        """
        Returns the full catalog of Bazaar item IDs.
        """
        return self._fetch_item_ids_list()

    def _fetch_item_ids_list(self) -> List[str]:
        now = time.time()
        if (
            not self._cached_item_ids
            or (now - self._last_item_ids_fetch) > self.config.STATIC_METADATA_TTL_SECONDS
        ):
            if self.config.USE_MOCK_API:
                mock_path = (
                    Path(__file__).resolve().parent.parent
                    / "fixtures"
                    / "bazaar-items.mock.json"
                )
                if mock_path.exists():
                    with open(mock_path, "r", encoding="utf-8") as f:
                        self._cached_item_ids = json.load(f)
                        self._last_item_ids_fetch = now
                        return self._cached_item_ids

            items = self.api_client.get_bazaar_items()
            self._cached_item_ids = items
            self._last_item_ids_fetch = now

        return self._cached_item_ids

    def _fetch_single_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        if self.config.USE_MOCK_API:
            mock_path = (
                Path(__file__).resolve().parent.parent
                / "fixtures"
                / "bazaar-item-details.mock.json"
            )
            if mock_path.exists():
                with open(mock_path, "r", encoding="utf-8") as f:
                    details_map = json.load(f)
                    if item_id in details_map:
                        return details_map[item_id]
                    raise UpstreamAPIError(f"Mock item {item_id} not found in fixture", 404)

        return self.api_client.get_bazaar_item_details(item_id)

    def execute_refresh_cycle(self) -> bool:
        """
        Executes one full refresh cycle with priority queue & 7.5s pacing.
        Thread-safe, non-overlapping.
        """
        if not self._refresh_lock.acquire(blocking=False):
            logger.info("Refresh cycle already in progress, coalescing trigger")
            return False

        self._cycle_running = True
        self.cache.set_refresh_in_progress(True)
        cycle_start_time = datetime.now(timezone.utc)
        logger.info("Starting Bazaar refresh cycle at %s", cycle_start_time.isoformat())

        try:
            # Step 1: obtain full item ID list
            try:
                all_item_ids = list(self._fetch_item_ids_list())
            except Exception as e:
                logger.error("Failed to fetch Bazaar item ID list: %s", e)
                self.cache.publish_cycle_results(new_items={}, refresh_succeeded=False)
                return False

            if not all_item_ids:
                logger.warning("No Bazaar items found in item ID list")
                self.cache.publish_cycle_results(new_items={}, refresh_succeeded=False)
                return False

            # Step 2: Prioritize queue
            #   1. Favorites (in DB order, already prioritised)
            #   2. Remaining items sorted by last_updated ascending
            #      (never-fetched items have empty string → sort to front)
            fav_list = self.db.get_favorites()
            fav_set = set(fav_list)

            cached_timestamps = self.cache.get_items_with_timestamps()

            priority_queue: List[str] = [i for i in fav_list if i in all_item_ids]

            remaining_items = [i for i in all_item_ids if i not in fav_set]
            # Sort by last_updated ISO string ascending; empty string sorts first
            remaining_items.sort(key=lambda i: cached_timestamps.get(i, ""))

            priority_queue.extend(remaining_items)

            with self._queue_lock:
                self._active_queue = list(priority_queue)

            total_items = len(priority_queue)
            completed_count = 0
            results: Dict[str, BazaarItemState] = {}
            failed_ids: List[str] = []

            # Step 3: Process queue sequentially with 7.5s pacing
            while True:
                if self._stop_event.is_set():
                    logger.info("Stopping refresh cycle early due to stop signal")
                    break

                with self._queue_lock:
                    if not self._active_queue:
                        break
                    item_id = self._active_queue.pop(0)

                self.cache.set_queue_progress(
                    completed=completed_count,
                    total=total_items,
                    current_item=item_id,
                )

                try:
                    raw_details = self._fetch_single_item(item_id)
                    if raw_details:
                        adapted = adapt_bazaar_item(
                            payload=raw_details,
                            tax_rate=self.config.BAZAAR_TAX_RATE,
                            enable_heuristic_profit_per_hour=self.config.ENABLE_HEURISTIC_PROFIT_PER_HOUR,
                            heuristic_volume_window_hours=self.config.HEURISTIC_VOLUME_WINDOW_HOURS,
                            fetch_time=datetime.now(timezone.utc),
                        )
                        results[item_id] = adapted

                        # Incrementally update cache so dashboard sees fresh item immediately
                        self.cache.upsert_item(adapted)

                        # Persist to SQLite if state changed
                        self.db.record_item_state(
                            adapted, captured_at=int(time.time())
                        )
                        completed_count += 1
                        logger.info(
                            "[%d/%d] Fetched %s (Spread: %.1f, Profit: %.1f)",
                            completed_count,
                            total_items,
                            item_id,
                            adapted.spread or 0.0,
                            adapted.profit_per_flip or 0.0,
                        )

                except RateLimitExceededError as rle:
                    retry_wait = getattr(rle, "retry_after", None) or 60.0
                    logger.warning(
                        "Upstream rate limit 429 for %s. Pausing queue for %.1fs then retying.",
                        item_id,
                        retry_wait,
                    )
                    # Re-insert item at front so it is retried next
                    with self._queue_lock:
                        self._active_queue.insert(0, item_id)
                    # Sleep for the lockout duration (with stop check)
                    if self._stop_event.wait(timeout=retry_wait + 1.0):
                        break
                    continue

                except Exception as err:
                    logger.warning("Failed to fetch details for %s: %s", item_id, err)
                    failed_ids.append(item_id)

                # Pace delay between requests (7.5s, or 0s in mock test mode)
                delay = (
                    0.0
                    if self.config.USE_MOCK_API
                    else self.config.UPSTREAM_REQUEST_DELAY_SECONDS
                )
                if delay > 0:
                    if self._stop_event.wait(timeout=delay):
                        break

            # Step 4: Finalize cycle
            cycle_success = len(results) > 0
            self.cache.publish_cycle_results(
                new_items=results,
                refresh_succeeded=cycle_success,
                failed_item_ids=failed_ids,
            )
            self.cache.set_queue_progress(
                completed=completed_count,
                total=total_items,
                current_item="",
            )

            # Step 5: Prune old history
            try:
                pruned = self.db.prune_old_snapshots(
                    retention_days=self.config.SNAPSHOT_RETENTION_DAYS
                )
                if pruned > 0:
                    logger.info("Pruned %d expired price snapshots", pruned)
            except Exception as e:
                logger.warning("Error pruning old snapshots: %s", e)

            logger.info(
                "Completed Bazaar cycle: %d/%d items updated",
                completed_count,
                total_items,
            )
            return cycle_success

        finally:
            self._cycle_running = False
            self.cache.set_refresh_in_progress(False)
            self._refresh_lock.release()
