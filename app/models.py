from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any


@dataclass
class BazaarItemState:
    item_id: str
    display_name: str
    buy_order_price: Optional[float]
    sell_offer_price: Optional[float]
    best_buy_quantity: Optional[int] = None
    best_sell_quantity: Optional[int] = None
    buy_volume: Optional[int] = None
    sell_volume: Optional[int] = None
    weekly_average_price: Optional[float] = None
    spread: Optional[float] = None
    tax_amount: Optional[float] = None
    profit_per_flip: Optional[float] = None
    roi_percent: Optional[float] = None
    profit_per_hour: Optional[float] = None
    candidate_quantity: Optional[int] = None
    required_budget: Optional[float] = None
    state_hash: str = ""
    last_updated: str = ""
    stale: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "itemId": self.item_id,
            "displayName": self.display_name,
            "buyOrderPrice": self.buy_order_price,
            "sellOfferPrice": self.sell_offer_price,
            "bestBuyQuantity": self.best_buy_quantity,
            "bestSellQuantity": self.best_sell_quantity,
            "buyVolume": self.buy_volume,
            "sellVolume": self.sell_volume,
            "weeklyAveragePrice": self.weekly_average_price,
            "spread": self.spread,
            "taxAmount": self.tax_amount,
            "profitPerFlip": self.profit_per_flip,
            "roiPercent": self.roi_percent,
            "profitPerHour": self.profit_per_hour,
            "candidateQuantity": self.candidate_quantity,
            "requiredBudget": self.required_budget,
            "stateHash": self.state_hash,
            "lastUpdated": self.last_updated,
            "stale": self.stale,
        }


@dataclass
class MarketSnapshot:
    generated_at: str
    last_refresh_at: str
    next_refresh_at: str
    stale: bool
    refresh_in_progress: bool
    version_hash: str
    items: List[BazaarItemState]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generatedAt": self.generated_at,
            "lastRefreshAt": self.last_refresh_at,
            "nextRefreshAt": self.next_refresh_at,
            "stale": self.stale,
            "refreshInProgress": self.refresh_in_progress,
            "versionHash": self.version_hash,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass
class HistoryPoint:
    captured_at: int
    buy_order_price: Optional[float]
    sell_offer_price: Optional[float]
    buy_volume: Optional[int]
    sell_volume: Optional[int]
    profit_per_flip: Optional[float]
    roi_percent: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capturedAt": self.captured_at,
            "buyOrderPrice": self.buy_order_price,
            "sellOfferPrice": self.sell_offer_price,
            "buyVolume": self.buy_volume,
            "sellVolume": self.sell_volume,
            "profitPerFlip": self.profit_per_flip,
            "roiPercent": self.roi_percent,
        }
