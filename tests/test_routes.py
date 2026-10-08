from unittest.mock import MagicMock
import pytest
from app import create_app
from app.api_client import CraftersMCClient
from app.config import Config
from app.models import BazaarItemState


@pytest.fixture
def test_app(tmp_path):
    db_file = str(tmp_path / "test_routes.db")
    config = Config(
        DB_PATH=db_file,
        PORT=5000,
        CACHE_TTL_SECONDS=600,
    )

    mock_client = MagicMock(spec=CraftersMCClient)
    # create_app without starting background loop to keep tests fully synchronous
    app = create_app(
        config_override=config,
        start_refresher=False,
        api_client_override=mock_client,
    )

    # Pre-populate cache with test data
    cache = app.extensions["cache"]
    item_diamond = BazaarItemState(
        item_id="ENCHANTED_DIAMOND",
        display_name="Enchanted Diamond",
        buy_order_price=1200.0,
        sell_offer_price=1450.0,
        best_buy_quantity=64,
        best_sell_quantity=64,
        spread=250.0,
        tax_amount=14.5,
        profit_per_flip=235.5,
        roi_percent=19.63,
        buy_volume=15000,
        sell_volume=12000,
        state_hash="hash_dia_test",
    )
    item_iron = BazaarItemState(
        item_id="ENCHANTED_IRON",
        display_name="Enchanted Iron",
        buy_order_price=500.0,
        sell_offer_price=600.0,
        best_buy_quantity=100,
        best_sell_quantity=80,
        spread=100.0,
        tax_amount=6.0,
        profit_per_flip=94.0,
        roi_percent=18.8,
        buy_volume=5000,
        sell_volume=4200,
        state_hash="hash_iron_test",
    )

    cache.publish_cycle_results(
        {"ENCHANTED_DIAMOND": item_diamond, "ENCHANTED_IRON": item_iron},
        refresh_succeeded=True,
    )

    # Also record to db for history queries
    db = app.extensions["db"]
    db.record_item_state(item_diamond)
    db.record_item_state(item_iron)

    return app, mock_client


def test_index_route(test_app):
    app, _ = test_app
    client = app.test_client()
    res = client.get("/")
    assert res.status_code == 200
    assert b"CraftersMC Bazaar Flip" in res.data


def test_api_market_etag_and_caching(test_app):
    app, mock_client = test_app
    client = app.test_client()

    # Reset call counts on mock_client to strictly verify zero upstream calls
    mock_client.reset_mock()

    res = client.get("/api/market")
    assert res.status_code == 200
    data = res.get_json()
    assert "items" in data
    assert len(data["items"]) == 2
    assert "ETag" in res.headers
    etag = res.headers["ETag"]

    # Verify conditional 304 Not Modified
    res_cached = client.get("/api/market", headers={"If-None-Match": etag})
    assert res_cached.status_code == 304

    # CRITICAL: Confirm zero upstream calls occurred during route handling
    assert mock_client.get_bazaar_items.call_count == 0
    assert mock_client.get_bazaar_item_details.call_count == 0


def test_api_market_filtering_and_search(test_app):
    app, _ = test_app
    client = app.test_client()

    # Search for diamond
    res = client.get("/api/market?search=diamond")
    data = res.get_json()
    assert len(data["items"]) == 1
    assert data["items"][0]["itemId"] == "ENCHANTED_DIAMOND"

    # Min profit filter
    res = client.get("/api/market?min_profit=200")
    data = res.get_json()
    assert len(data["items"]) == 1
    assert data["items"][0]["itemId"] == "ENCHANTED_DIAMOND"

    # Favorites filter
    res = client.get(
        "/api/market?favorites_only=true&favorites=ENCHANTED_IRON"
    )
    data = res.get_json()
    assert len(data["items"]) == 1
    assert data["items"][0]["itemId"] == "ENCHANTED_IRON"


def test_api_item_detail_and_history(test_app):
    app, mock_client = test_app
    client = app.test_client()
    mock_client.reset_mock()

    res = client.get("/api/items/ENCHANTED_DIAMOND")
    assert res.status_code == 200
    data = res.get_json()
    assert data["item"]["itemId"] == "ENCHANTED_DIAMOND"
    assert "history" in data
    assert "disclaimer" in data

    # Unknown item returns 404
    res_missing = client.get("/api/items/NON_EXISTENT")
    assert res_missing.status_code == 404

    # Upstream client was never contacted
    assert mock_client.get_bazaar_item_details.call_count == 0


def test_api_status_and_refresh(test_app):
    app, _ = test_app
    client = app.test_client()

    res_status = client.get("/api/status")
    assert res_status.status_code == 200
    status = res_status.get_json()
    assert status["totalItems"] == 2
    assert status["stale"] is False

    res_refresh = client.post("/api/refresh")
    assert res_refresh.status_code == 200
    assert res_refresh.get_json()["status"] in ("triggered", "already_running")


def test_api_favorites_and_catalog(test_app):
    app, mock_client = test_app
    mock_client.get_bazaar_items.return_value = ["ENCHANTED_DIAMOND", "ENCHANTED_IRON"]
    client = app.test_client()

    # Get catalog
    res_cat = client.get("/api/items/catalog")
    assert res_cat.status_code == 200
    cat = res_cat.get_json()
    assert "catalog" in cat
    assert len(cat["catalog"]) == 2

    # Post favorite
    res_fav = client.post(
        "/api/favorites",
        json={"itemId": "ENCHANTED_DIAMOND", "isFavorite": True},
    )
    assert res_fav.status_code == 200
    favs = res_fav.get_json()["favorites"]
    assert "ENCHANTED_DIAMOND" in favs

    # Get favorites
    res_get_fav = client.get("/api/favorites")
    assert res_get_fav.status_code == 200
    assert "ENCHANTED_DIAMOND" in res_get_fav.get_json()["favorites"]

