import time
from unittest.mock import MagicMock
from app.api_client import CraftersMCClient, RateLimitExceededError
from app.cache import MarketCache
from app.config import Config
from app.db import Database
from app.refresher import BazaarRefresher


def test_refresher_cycle_with_mock_client(tmp_path):
    db_file = str(tmp_path / "test_bazaar.db")
    db = Database(db_file)
    cache = MarketCache(ttl_seconds=600)

    config = Config(
        DB_PATH=db_file,
        UPSTREAM_MAX_CONCURRENCY=2,
        SNAPSHOT_RETENTION_DAYS=7,
        USE_MOCK_API=False,
        UPSTREAM_REQUEST_DELAY_SECONDS=0.0,
    )

    mock_client = MagicMock(spec=CraftersMCClient)
    mock_client.get_bazaar_items.return_value = ["MOCK_ITEM_1", "MOCK_ITEM_2"]
    mock_client.get_bazaar_item_details.side_effect = [
        {
            "success": True,
            "itemId": "MOCK_ITEM_1",
            "buyTopEntries": [{"price": 100.0, "quantity": 10}],
            "sellTopEntries": [{"price": 120.0, "quantity": 10}],
            "buyVolume": 1000,
            "sellVolume": 900,
        },
        {
            "success": True,
            "itemId": "MOCK_ITEM_2",
            "buyTopEntries": [{"price": 200.0, "quantity": 5}],
            "sellTopEntries": [{"price": 250.0, "quantity": 5}],
            "buyVolume": 500,
            "sellVolume": 400,
        },
    ]

    refresher = BazaarRefresher(
        config=config,
        cache=cache,
        db=db,
        api_client=mock_client,
    )

    success = refresher.execute_refresh_cycle()
    assert success is True

    snapshot = cache.get_snapshot()
    assert len(snapshot.items) == 2
    assert cache.stale is False

    # Check DB persistence
    latest_1 = db.get_latest_snapshot("MOCK_ITEM_1")
    assert latest_1 is not None
    assert latest_1["buy_order_price"] == 100.0
    assert latest_1["sell_offer_price"] == 120.0

    # Test snapshot deduplication: run second cycle with same data
    mock_client.get_bazaar_item_details.side_effect = [
        {
            "success": True,
            "itemId": "MOCK_ITEM_1",
            "buyTopEntries": [{"price": 100.0, "quantity": 10}],
            "sellTopEntries": [{"price": 120.0, "quantity": 10}],
            "buyVolume": 1000,
            "sellVolume": 900,
        },
        {
            "success": True,
            "itemId": "MOCK_ITEM_2",
            "buyTopEntries": [{"price": 200.0, "quantity": 5}],
            "sellTopEntries": [{"price": 250.0, "quantity": 5}],
            "buyVolume": 500,
            "sellVolume": 400,
        },
    ]

    refresher.execute_refresh_cycle()

    # Verify no second snapshot created in DB because data did not change
    with db.get_connection() as conn:
        count = conn.execute(
            "SELECT count(*) FROM price_snapshots WHERE item_id = 'MOCK_ITEM_1'"
        ).fetchone()[0]
        assert count == 1  # Exactly 1 row persisted, no duplicate!


def test_refresher_priority_queue_favorites_first(tmp_path):
    db_file = str(tmp_path / "test_prio.db")
    db = Database(db_file)
    cache = MarketCache(ttl_seconds=600)

    # Set favorite in DB
    db.set_favorite("FAVORITE_ITEM", True)

    config = Config(
        DB_PATH=db_file,
        USE_MOCK_API=False,
        UPSTREAM_REQUEST_DELAY_SECONDS=0.0,
    )

    call_order = []

    def mock_fetch(item_id):
        call_order.append(item_id)
        return {
            "success": True,
            "itemId": item_id,
            "buyTopEntries": [{"price": 10.0, "quantity": 1}],
            "sellTopEntries": [{"price": 15.0, "quantity": 1}],
        }

    mock_client = MagicMock(spec=CraftersMCClient)
    mock_client.get_bazaar_items.return_value = ["NORMAL_A", "NORMAL_B", "FAVORITE_ITEM"]
    mock_client.get_bazaar_item_details.side_effect = mock_fetch

    refresher = BazaarRefresher(
        config=config,
        cache=cache,
        db=db,
        api_client=mock_client,
    )

    success = refresher.execute_refresh_cycle()
    assert success is True

    # FAVORITE_ITEM must be fetched first because it's bumped to the front!
    assert call_order[0] == "FAVORITE_ITEM"
    assert set(call_order) == {"FAVORITE_ITEM", "NORMAL_A", "NORMAL_B"}


def test_database_retention_pruning(tmp_path):
    db_file = str(tmp_path / "test_prune.db")
    db = Database(db_file)

    now = int(time.time())
    old_timestamp = now - (8 * 86400)  # 8 days ago (> 7 days)
    recent_timestamp = now - (2 * 86400)  # 2 days ago

    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO items (item_id, display_name, created_at, updated_at) VALUES ('OLD_ITEM', 'Old', '', '')"
        )
        # Old snapshot
        conn.execute(
            """
            INSERT INTO price_snapshots (item_id, captured_at, buy_order_price, state_hash)
            VALUES ('OLD_ITEM', ?, 10.0, 'hash_old');
            """,
            (old_timestamp,),
        )
        # Recent snapshot
        conn.execute(
            """
            INSERT INTO price_snapshots (item_id, captured_at, buy_order_price, state_hash)
            VALUES ('OLD_ITEM', ?, 12.0, 'hash_recent');
            """,
            (recent_timestamp,),
        )
        conn.commit()

    pruned = db.prune_old_snapshots(retention_days=7)
    assert pruned == 1

    with db.get_connection() as conn:
        remaining = conn.execute("SELECT count(*) FROM price_snapshots").fetchone()[0]
        assert remaining == 1
