import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from app.models import BazaarItemState, HistoryPoint


class Database:
    """
    SQLite persistence layer for Bazaar items and historical price snapshots.
    Implements change-detection deduplication and 7-day retention pruning.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_dir()
        self.init_db()

    def _ensure_dir(self) -> None:
        p = Path(self.db_path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def init_db(self) -> None:
        with self.get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    item_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS price_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id TEXT NOT NULL,
                    captured_at INTEGER NOT NULL,
                    buy_order_price REAL,
                    sell_offer_price REAL,
                    buy_volume INTEGER,
                    sell_volume INTEGER,
                    spread REAL,
                    tax_amount REAL,
                    profit_per_flip REAL,
                    roi_percent REAL,
                    state_hash TEXT NOT NULL,
                    FOREIGN KEY(item_id) REFERENCES items(item_id)
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS favorites (
                    item_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_snapshots_item_time
                ON price_snapshots(item_id, captured_at);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_snapshots_time
                ON price_snapshots(captured_at);
                """
            )
            conn.commit()

    def get_latest_snapshot(self, item_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves the most recent stored snapshot for an item.
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM price_snapshots
                WHERE item_id = ?
                ORDER BY captured_at DESC, id DESC
                LIMIT 1;
                """,
                (item_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def record_item_state(
        self, item: BazaarItemState, captured_at: Optional[int] = None
    ) -> bool:
        """
        Persists item metadata and adds a price_snapshot ONLY IF the state_hash
        has changed from the last stored snapshot.
        Returns True if a new snapshot was persisted, False if deduplicated.
        """
        timestamp = captured_at if captured_at is not None else int(time.time())
        iso_now = datetime.now(timezone.utc).isoformat()

        latest = self.get_latest_snapshot(item.item_id)
        if latest and latest.get("state_hash") == item.state_hash:
            # Unchanged, skip creating redundant snapshot
            return False

        with self.get_connection() as conn:
            # Upsert item metadata
            conn.execute(
                """
                INSERT INTO items (item_id, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    updated_at = excluded.updated_at;
                """,
                (item.item_id, item.display_name, iso_now, iso_now),
            )

            # Insert new snapshot
            conn.execute(
                """
                INSERT INTO price_snapshots (
                    item_id, captured_at, buy_order_price, sell_offer_price,
                    buy_volume, sell_volume, spread, tax_amount,
                    profit_per_flip, roi_percent, state_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    item.item_id,
                    timestamp,
                    item.buy_order_price,
                    item.sell_offer_price,
                    item.buy_volume,
                    item.sell_volume,
                    item.spread,
                    item.tax_amount,
                    item.profit_per_flip,
                    item.roi_percent,
                    item.state_hash,
                ),
            )
            conn.commit()

        return True

    def prune_old_snapshots(self, retention_days: int = 7) -> int:
        """
        Prunes snapshot records older than the retention threshold.
        """
        cutoff_timestamp = int(time.time()) - (retention_days * 86400)
        with self.get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM price_snapshots WHERE captured_at < ?;",
                (cutoff_timestamp,),
            )
            deleted_count = cursor.rowcount
            conn.commit()
        return deleted_count

    def get_history(
        self, item_id: str, window_seconds: int = 86400
    ) -> List[HistoryPoint]:
        """
        Returns historical points for an item within the requested lookback window.
        """
        cutoff = int(time.time()) - window_seconds
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT captured_at, buy_order_price, sell_offer_price,
                       buy_volume, sell_volume, profit_per_flip, roi_percent
                FROM price_snapshots
                WHERE item_id = ? AND captured_at >= ?
                ORDER BY captured_at ASC;
                """,
                (item_id, cutoff),
            )
            points = []
            for row in cursor.fetchall():
                points.append(
                    HistoryPoint(
                        captured_at=row["captured_at"],
                        buy_order_price=row["buy_order_price"],
                        sell_offer_price=row["sell_offer_price"],
                        buy_volume=row["buy_volume"],
                        sell_volume=row["sell_volume"],
                        profit_per_flip=row["profit_per_flip"],
                        roi_percent=row["roi_percent"],
                    )
                )
            return points

    def get_snapshot_at_or_before(
        self, item_id: str, target_timestamp: int
    ) -> Optional[Dict[str, Any]]:
        """
        Finds the snapshot closest to but at or before target_timestamp.
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM price_snapshots
                WHERE item_id = ? AND captured_at <= ?
                ORDER BY captured_at DESC
                LIMIT 1;
                """,
                (item_id, target_timestamp),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def load_latest_states(self) -> List[Dict[str, Any]]:
        """
        Loads the most recent snapshot for every stored item for warm startup.
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT p.*, i.display_name
                FROM price_snapshots p
                JOIN (
                    SELECT item_id, MAX(captured_at) as max_time
                    FROM price_snapshots
                    GROUP BY item_id
                ) latest ON p.item_id = latest.item_id AND p.captured_at = latest.max_time
                JOIN items i ON p.item_id = i.item_id;
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_favorites(self) -> List[str]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT item_id FROM favorites ORDER BY created_at ASC;")
            return [row["item_id"] for row in cursor.fetchall()]

    def set_favorite(self, item_id: str, is_favorite: bool) -> None:
        with self.get_connection() as conn:
            if is_favorite:
                iso_now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT OR IGNORE INTO favorites (item_id, created_at) VALUES (?, ?);",
                    (item_id, iso_now),
                )
            else:
                conn.execute("DELETE FROM favorites WHERE item_id = ?;", (item_id,))
            conn.commit()

    def set_all_favorites(self, item_ids: List[str]) -> None:
        iso_now = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute("DELETE FROM favorites;")
            for item_id in item_ids:
                conn.execute(
                    "INSERT INTO favorites (item_id, created_at) VALUES (?, ?);",
                    (item_id, iso_now),
                )
            conn.commit()

