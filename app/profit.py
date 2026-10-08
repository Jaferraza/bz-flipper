from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple, List
from app.models import BazaarItemState


def round_decimal(val: Optional[Decimal], places: int = 2) -> Optional[float]:
    if val is None:
        return None
    q = Decimal(10) ** -places
    return float(val.quantize(q, rounding=ROUND_HALF_UP))


def compute_metrics(
    buy_order_price: Optional[float],
    sell_offer_price: Optional[float],
    tax_rate: float = 0.01,
    best_buy_quantity: Optional[int] = None,
    best_sell_quantity: Optional[int] = None,
    buy_volume: Optional[int] = None,
    sell_volume: Optional[int] = None,
    enable_heuristic_profit_per_hour: bool = False,
    heuristic_volume_window_hours: float = 1.0,
) -> Tuple[
    Optional[float],  # spread
    Optional[float],  # tax_amount
    Optional[float],  # profit_per_flip
    Optional[float],  # roi_percent
    Optional[float],  # profit_per_hour
    Optional[int],  # candidate_quantity
    Optional[float],  # required_budget
]:
    """
    Computes spread, tax, profit_per_flip, roi_percent, profit_per_hour, and budget.
    Uses Decimal arithmetic to prevent binary floating-point inaccuracy.
    """
    if buy_order_price is None or sell_offer_price is None:
        return None, None, None, None, None, None, None

    try:
        buy_dec = Decimal(str(buy_order_price))
        sell_dec = Decimal(str(sell_offer_price))
        tax_rate_dec = Decimal(str(tax_rate))
    except Exception:
        return None, None, None, None, None, None, None

    spread_dec = sell_dec - buy_dec
    tax_amount_dec = sell_dec * tax_rate_dec
    profit_dec = spread_dec - tax_amount_dec

    spread = round_decimal(spread_dec, 2)
    tax_amount = round_decimal(tax_amount_dec, 2)
    profit_per_flip = round_decimal(profit_dec, 2)

    # ROI guard
    if buy_dec <= Decimal("0"):
        roi_percent = None
    else:
        roi_dec = (profit_dec / buy_dec) * Decimal("100")
        roi_percent = round_decimal(roi_dec, 2)

    # Candidate quantity & required budget
    candidate_quantity: Optional[int] = None
    required_budget: Optional[float] = None
    if (
        best_buy_quantity is not None
        and best_sell_quantity is not None
        and best_buy_quantity > 0
        and best_sell_quantity > 0
    ):
        candidate_quantity = min(best_buy_quantity, best_sell_quantity)
        required_budget = round_decimal(buy_dec * Decimal(candidate_quantity), 2)
    elif best_buy_quantity is not None and best_buy_quantity > 0:
        candidate_quantity = best_buy_quantity
        required_budget = round_decimal(buy_dec * Decimal(candidate_quantity), 2)

    # Profit per hour (heuristic or unavailable)
    profit_per_hour: Optional[float] = None
    if enable_heuristic_profit_per_hour and heuristic_volume_window_hours > 0:
        if (
            buy_volume is not None
            and sell_volume is not None
            and profit_per_flip is not None
        ):
            min_vol = min(buy_volume, sell_volume)
            flips_per_hour = Decimal(str(min_vol)) / Decimal(
                str(heuristic_volume_window_hours)
            )
            profit_per_hour_dec = profit_dec * flips_per_hour
            profit_per_hour = round_decimal(profit_per_hour_dec, 2)

    return (
        spread,
        tax_amount,
        profit_per_flip,
        roi_percent,
        profit_per_hour,
        candidate_quantity,
        required_budget,
    )


def is_good_buy_suggestion(
    item: BazaarItemState,
    min_profit: Optional[float] = None,
    min_volume: Optional[int] = None,
    budget_cap: Optional[float] = None,
) -> bool:
    """
    Excludes an item from good-buy suggestions when:
    - buy-order price missing
    - sell-offer price missing
    - profit is non-positive (<= 0)
    - fails minimum volume/profit thresholds
    - exceeds budget cap (if enabled and required budget is computed)
    """
    if item.buy_order_price is None or item.sell_offer_price is None:
        return False

    if item.profit_per_flip is None or item.profit_per_flip <= 0:
        return False

    if min_profit is not None and item.profit_per_flip < min_profit:
        return False

    if min_volume is not None:
        item_vol = min(item.buy_volume or 0, item.sell_volume or 0)
        if item_vol < min_volume:
            return False

    if budget_cap is not None and item.required_budget is not None:
        if item.required_budget > budget_cap:
            return False

    return True


def rank_items(items: List[BazaarItemState]) -> List[BazaarItemState]:
    """
    Deterministic flip ranking:
    1. Positive profit_per_flip descending (nulls last)
    2. ROI percent descending (nulls last)
    3. Sell volume descending (nulls last)
    4. item_id ascending
    """

    def sort_key(item: BazaarItemState):
        profit = item.profit_per_flip if item.profit_per_flip is not None else -1e12
        roi = item.roi_percent if item.roi_percent is not None else -1e12
        vol = item.sell_volume if item.sell_volume is not None else -1
        return (-profit, -roi, -vol, item.item_id)

    return sorted(items, key=sort_key)
