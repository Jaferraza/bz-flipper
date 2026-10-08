from app.cache import MarketCache
from app.models import BazaarItemState


def test_market_cache_lifecycle():
    cache = MarketCache(ttl_seconds=600)
    assert cache.stale is True  # Starts stale

    item1 = BazaarItemState(
        item_id="IRON",
        display_name="Iron",
        buy_order_price=50.0,
        sell_offer_price=60.0,
        profit_per_flip=9.4,
        state_hash="hash_iron_1",
    )
    item2 = BazaarItemState(
        item_id="GOLD",
        display_name="Gold",
        buy_order_price=100.0,
        sell_offer_price=150.0,
        profit_per_flip=48.5,
        state_hash="hash_gold_1",
    )

    # Publish successful cycle
    cache.publish_cycle_results(
        new_items={"IRON": item1, "GOLD": item2},
        refresh_succeeded=True,
    )

    assert cache.stale is False
    assert cache.last_refresh_at is not None
    assert cache.successful_refresh_cycles == 1

    snapshot = cache.get_snapshot()
    assert len(snapshot.items) == 2
    # GOLD has higher profit, ranked first
    assert snapshot.items[0].item_id == "GOLD"
    assert snapshot.items[1].item_id == "IRON"
    initial_version = snapshot.version_hash

    # Test partial refresh where GOLD fails
    item1_updated = BazaarItemState(
        item_id="IRON",
        display_name="Iron",
        buy_order_price=52.0,
        sell_offer_price=62.0,
        profit_per_flip=9.38,
        state_hash="hash_iron_2",
    )
    cache.publish_cycle_results(
        new_items={"IRON": item1_updated},
        refresh_succeeded=True,
        failed_item_ids=["GOLD"],
    )

    # GOLD should retain its prior state but be marked stale
    gold = cache.get_item("GOLD")
    assert gold is not None
    assert gold.buy_order_price == 100.0  # Retained
    assert gold.stale is True  # Marked stale

    iron = cache.get_item("IRON")
    assert iron is not None
    assert iron.buy_order_price == 52.0
    assert iron.stale is False

    # Version hash should have updated
    snapshot2 = cache.get_snapshot()
    assert snapshot2.version_hash != initial_version


def test_market_cache_total_failure_preservation():
    cache = MarketCache(ttl_seconds=600)
    item = BazaarItemState(
        item_id="DIAMOND",
        display_name="Diamond",
        buy_order_price=1000.0,
        sell_offer_price=1200.0,
        profit_per_flip=188.0,
        state_hash="hash_dia",
    )
    cache.publish_cycle_results({"DIAMOND": item}, refresh_succeeded=True)
    assert cache.stale is False

    # Total failure in next cycle
    cache.publish_cycle_results({}, refresh_succeeded=False)

    # Cached items must NOT be wiped or replaced with nulls
    assert cache.stale is True
    diamond = cache.get_item("DIAMOND")
    assert diamond is not None
    assert diamond.profit_per_flip == 188.0


def test_warm_from_db():
    cache = MarketCache(ttl_seconds=600)
    db_rows = [
        {
            "item_id": "EMERALD",
            "display_name": "Emerald",
            "captured_at": 1700000000,
            "buy_order_price": 500.0,
            "sell_offer_price": 600.0,
            "buy_volume": 100,
            "sell_volume": 90,
            "spread": 100.0,
            "tax_amount": 6.0,
            "profit_per_flip": 94.0,
            "roi_percent": 18.8,
            "state_hash": "hash_em",
        }
    ]

    cache.warm_from_db(db_rows)
    item = cache.get_item("EMERALD")
    assert item is not None
    assert item.buy_order_price == 500.0
    assert item.profit_per_flip == 94.0
    assert item.stale is True  # Warmed items start stale until fresh sync
