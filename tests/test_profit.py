from app.profit import compute_metrics, is_good_buy_suggestion, rank_items
from app.models import BazaarItemState


def test_compute_metrics_standard():
    # Buy at 100, sell at 120, 1% tax on sell proceeds (1.20)
    # Gross spread = 20.0
    # Net profit = 120 - 100 - 1.2 = 18.8
    # ROI = 18.8 / 100 * 100 = 18.8%
    spread, tax, profit, roi, pph, qty, budget = compute_metrics(
        buy_order_price=100.0,
        sell_offer_price=120.0,
        tax_rate=0.01,
        best_buy_quantity=50,
        best_sell_quantity=40,
        buy_volume=1000,
        sell_volume=800,
    )

    assert spread == 20.0
    assert tax == 1.2
    assert profit == 18.8
    assert roi == 18.8
    assert pph is None  # Profit per hour unavailable by default
    assert qty == 40  # Min(50, 40)
    assert budget == 4000.0  # 100 * 40


def test_compute_metrics_missing_prices():
    # Missing sell side
    spread, tax, profit, roi, pph, qty, budget = compute_metrics(
        buy_order_price=100.0,
        sell_offer_price=None,
    )
    assert spread is None
    assert tax is None
    assert profit is None
    assert roi is None
    assert pph is None


def test_compute_metrics_zero_buy_price():
    # Guard against divide by zero
    spread, tax, profit, roi, pph, qty, budget = compute_metrics(
        buy_order_price=0.0,
        sell_offer_price=50.0,
    )
    assert spread == 50.0
    assert profit == 49.5
    assert roi is None  # Guarded, not ZeroDivisionError


def test_heuristic_profit_per_hour():
    # Test opt-in heuristic profit per hour
    spread, tax, profit, roi, pph, qty, budget = compute_metrics(
        buy_order_price=100.0,
        sell_offer_price=120.0,
        tax_rate=0.01,
        buy_volume=500,
        sell_volume=200,
        enable_heuristic_profit_per_hour=True,
        heuristic_volume_window_hours=1.0,
    )
    assert profit == 18.8
    # Min volume = 200. Flips/hr = 200. 18.8 * 200 = 3760.0
    assert pph == 3760.0


def test_is_good_buy_suggestion_filtering():
    profitable_item = BazaarItemState(
        item_id="DIAMOND",
        display_name="Diamond",
        buy_order_price=100.0,
        sell_offer_price=150.0,
        profit_per_flip=48.5,
        buy_volume=500,
        sell_volume=500,
        required_budget=2000.0,
    )

    unprofitable_item = BazaarItemState(
        item_id="DIRT",
        display_name="Dirt",
        buy_order_price=10.0,
        sell_offer_price=10.0,
        profit_per_flip=-0.1,
        buy_volume=100,
        sell_volume=100,
    )

    assert is_good_buy_suggestion(profitable_item) is True
    assert is_good_buy_suggestion(unprofitable_item) is False

    # Min profit threshold
    assert is_good_buy_suggestion(profitable_item, min_profit=50.0) is False
    assert is_good_buy_suggestion(profitable_item, min_profit=40.0) is True

    # Min volume threshold
    assert is_good_buy_suggestion(profitable_item, min_volume=1000) is False
    assert is_good_buy_suggestion(profitable_item, min_volume=200) is True

    # Budget cap
    assert is_good_buy_suggestion(profitable_item, budget_cap=1500.0) is False
    assert is_good_buy_suggestion(profitable_item, budget_cap=2500.0) is True


def test_deterministic_ranking():
    item_a = BazaarItemState(
        item_id="ITEM_A",
        display_name="Item A",
        buy_order_price=100.0,
        sell_offer_price=110.0,
        profit_per_flip=8.9,
        roi_percent=8.9,
        sell_volume=500,
    )
    item_b = BazaarItemState(
        item_id="ITEM_B",
        display_name="Item B",
        buy_order_price=100.0,
        sell_offer_price=130.0,
        profit_per_flip=28.7,
        roi_percent=28.7,
        sell_volume=300,
    )
    item_c = BazaarItemState(
        item_id="ITEM_C",
        display_name="Item C",
        buy_order_price=100.0,
        sell_offer_price=100.0,
        profit_per_flip=-1.0,
        roi_percent=-1.0,
        sell_volume=100,
    )

    ranked = rank_items([item_a, item_c, item_b])
    assert ranked[0].item_id == "ITEM_B"  # Highest profit
    assert ranked[1].item_id == "ITEM_A"
    assert ranked[2].item_id == "ITEM_C"
