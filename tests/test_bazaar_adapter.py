from app.bazaar_adapter import (
    adapt_bazaar_item,
    derive_display_name,
    extract_best_order_book,
    compute_state_hash,
)


def test_derive_display_name():
    assert derive_display_name("ENCHANTED_DIAMOND") == "Enchanted Diamond"
    assert derive_display_name("SUPER_COMPACTOR_3000") == "Super Compactor 3000"
    assert derive_display_name("WOOD") == "Wood"


def test_order_book_best_price_selection():
    # Buy side: index 0 is 100.0, index 1 is 120.0 -> Best buy bid is 120.0
    # Sell side: index 0 is 150.0, index 1 is 140.0 -> Best sell ask is 140.0
    buy_entries = [
        {"price": 100.0, "quantity": 10, "orderCount": 1},
        {"price": 120.0, "quantity": 30, "orderCount": 3},
    ]
    sell_entries = [
        {"price": 150.0, "quantity": 25, "orderCount": 2},
        {"price": 140.0, "quantity": 15, "orderCount": 4},
    ]

    best_buy, buy_qty, best_sell, sell_qty = extract_best_order_book(
        buy_entries, sell_entries
    )

    assert best_buy == 120.0
    assert buy_qty == 30
    assert best_sell == 140.0
    assert sell_qty == 15


def test_order_book_empty_handling():
    best_buy, buy_qty, best_sell, sell_qty = extract_best_order_book([], [])
    assert best_buy is None
    assert buy_qty is None
    assert best_sell is None
    assert sell_qty is None


def test_adapt_bazaar_item_mapping():
    payload = {
        "success": True,
        "itemId": "ENCHANTED_EMERALD",
        "buyTopEntries": [
            {"price": 800.0, "quantity": 64, "orderCount": 2},
            {"price": 850.0, "quantity": 128, "orderCount": 4},
        ],
        "sellTopEntries": [
            {"price": 1000.0, "quantity": 50, "orderCount": 3},
            {"price": 950.0, "quantity": 75, "orderCount": 5},
        ],
        "buyVolume": 5000,
        "sellVolume": 4000,
        "weeklyAveragePrice": 900.0,
    }

    item = adapt_bazaar_item(payload, tax_rate=0.01)

    assert item.item_id == "ENCHANTED_EMERALD"
    assert item.display_name == "Enchanted Emerald"
    assert item.buy_order_price == 850.0  # Max buy price
    assert item.sell_offer_price == 950.0  # Min sell price
    assert item.spread == 100.0
    assert item.tax_amount == 9.5  # 950 * 0.01
    assert item.profit_per_flip == 90.5  # 100 - 9.5
    assert item.candidate_quantity == 75  # Min(128, 75)
    assert item.required_budget == 63750.0  # 850 * 75
    assert len(item.state_hash) == 64


def test_compute_state_hash_determinism():
    hash1 = compute_state_hash("DIAMOND", 100.0, 120.0, 500, 400)
    hash2 = compute_state_hash("DIAMOND", 100.0, 120.0, 500, 400)
    hash3 = compute_state_hash("DIAMOND", 100.0, 125.0, 500, 400)

    assert hash1 == hash2
    assert hash1 != hash3
