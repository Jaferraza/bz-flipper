import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, List
from app.models import BazaarItemState
from app.profit import compute_metrics


def derive_display_name(item_id: str) -> str:
    """
    Derives readable label from item_id.
    Replaces underscores with spaces and applies title casing.
    """
    if not item_id:
        return ""
    words = item_id.replace("_", " ").split()
    return " ".join(word.capitalize() for word in words)


def extract_best_order_book(
    buy_entries: Optional[List[Dict[str, Any]]],
    sell_entries: Optional[List[Dict[str, Any]]],
) -> Tuple[
    Optional[float], Optional[int], Optional[float], Optional[int]
]:  # (best_buy_price, best_buy_qty, best_sell_price, best_sell_qty)
    best_buy_price: Optional[float] = None
    best_buy_qty: Optional[int] = None
    best_sell_price: Optional[float] = None
    best_sell_qty: Optional[int] = None

    if buy_entries and isinstance(buy_entries, list):
        valid_buys = [e for e in buy_entries if isinstance(e, dict) and "price" in e and e["price"] is not None]
        if valid_buys:
            # Maximum price among buyTopEntries is highest current bid
            best_buy = max(valid_buys, key=lambda e: float(e["price"]))
            best_buy_price = float(best_buy["price"])
            best_buy_qty = int(best_buy.get("quantity", 0)) if best_buy.get("quantity") is not None else None

    if sell_entries and isinstance(sell_entries, list):
        valid_sells = [e for e in sell_entries if isinstance(e, dict) and "price" in e and e["price"] is not None]
        if valid_sells:
            # Minimum price among sellTopEntries is lowest current ask
            best_sell = min(valid_sells, key=lambda e: float(e["price"]))
            best_sell_price = float(best_sell["price"])
            best_sell_qty = int(best_sell.get("quantity", 0)) if best_sell.get("quantity") is not None else None

    return best_buy_price, best_buy_qty, best_sell_price, best_sell_qty


def compute_state_hash(
    item_id: str,
    buy_order_price: Optional[float],
    sell_offer_price: Optional[float],
    buy_volume: Optional[int],
    sell_volume: Optional[int],
) -> str:
    """
    Computes deterministic SHA-256 state hash of core historical fields.
    """
    canonical_payload = {
        "item_id": item_id,
        "buy_order_price": buy_order_price,
        "sell_offer_price": sell_offer_price,
        "buy_volume": buy_volume,
        "sell_volume": sell_volume,
    }
    payload_str = json.dumps(canonical_payload, sort_keys=True)
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()


def adapt_bazaar_item(
    payload: Dict[str, Any],
    tax_rate: float = 0.01,
    enable_heuristic_profit_per_hour: bool = False,
    heuristic_volume_window_hours: float = 1.0,
    fetch_time: Optional[datetime] = None,
) -> BazaarItemState:
    """
    Adapts upstream BazaarItemReply into domain BazaarItemState.
    """
    item_id = str(payload.get("itemId", ""))
    display_name = derive_display_name(item_id)

    buy_entries = payload.get("buyTopEntries") or []
    sell_entries = payload.get("sellTopEntries") or []

    best_buy_price, best_buy_qty, best_sell_price, best_sell_qty = (
        extract_best_order_book(buy_entries, sell_entries)
    )

    buy_volume = payload.get("buyVolume")
    if buy_volume is not None:
        buy_volume = int(buy_volume)

    sell_volume = payload.get("sellVolume")
    if sell_volume is not None:
        sell_volume = int(sell_volume)

    weekly_avg = payload.get("weeklyAveragePrice")
    weekly_average_price = float(weekly_avg) if weekly_avg is not None else None

    # Compute metrics
    (
        spread,
        tax_amount,
        profit_per_flip,
        roi_percent,
        profit_per_hour,
        candidate_quantity,
        required_budget,
    ) = compute_metrics(
        buy_order_price=best_buy_price,
        sell_offer_price=best_sell_price,
        tax_rate=tax_rate,
        best_buy_quantity=best_buy_qty,
        best_sell_quantity=best_sell_qty,
        buy_volume=buy_volume,
        sell_volume=sell_volume,
        enable_heuristic_profit_per_hour=enable_heuristic_profit_per_hour,
        heuristic_volume_window_hours=heuristic_volume_window_hours,
    )

    state_hash = compute_state_hash(
        item_id=item_id,
        buy_order_price=best_buy_price,
        sell_offer_price=best_sell_price,
        buy_volume=buy_volume,
        sell_volume=sell_volume,
    )

    iso_fetch_time = (
        (fetch_time or datetime.now(timezone.utc)).isoformat()
    )

    return BazaarItemState(
        item_id=item_id,
        display_name=display_name,
        buy_order_price=best_buy_price,
        sell_offer_price=best_sell_price,
        best_buy_quantity=best_buy_qty,
        best_sell_quantity=best_sell_qty,
        buy_volume=buy_volume,
        sell_volume=sell_volume,
        weekly_average_price=weekly_average_price,
        spread=spread,
        tax_amount=tax_amount,
        profit_per_flip=profit_per_flip,
        roi_percent=roi_percent,
        profit_per_hour=profit_per_hour,
        candidate_quantity=candidate_quantity,
        required_budget=required_budget,
        state_hash=state_hash,
        last_updated=iso_fetch_time,
        stale=False,
    )
