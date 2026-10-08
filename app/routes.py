import hashlib
from flask import Blueprint, jsonify, render_template, request, make_response, current_app
from app.services import DashboardService
from app.refresher import BazaarRefresher

bp = Blueprint("main", __name__)


def get_service() -> DashboardService:
    return current_app.extensions["dashboard_service"]


def get_refresher() -> BazaarRefresher:
    return current_app.extensions["bazaar_refresher"]


@bp.route("/")
def index():
    """
    Renders the dashboard single-page shell.
    """
    return render_template("index.html")


@bp.route("/api/market", methods=["GET"])
def get_market():
    """
    Returns current cached Bazaar rows with derived metrics.
    Supports query parameters and returns ETag / 304 Not Modified.
    Never invokes the upstream API.
    """
    service = get_service()

    search = request.args.get("search", None)
    sort_by = request.args.get("sort_by", "profit")
    sort_dir = request.args.get("sort_dir", "desc")
    min_profit = request.args.get("min_profit", type=float)
    min_volume = request.args.get("min_volume", type=int)
    budget_cap = request.args.get("budget_cap", type=float)
    favorites_param = request.args.get("favorites", "")
    favorites = [f.strip() for f in favorites_param.split(",") if f.strip()]
    favorites_only = request.args.get("favorites_only", "false").lower() in ("true", "1")
    lookback_window = request.args.get("lookback_window", "1h")

    data = service.get_market_data(
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        min_profit=min_profit,
        min_volume=min_volume,
        budget_cap=budget_cap,
        favorites=favorites,
        favorites_only=favorites_only,
        lookback_window=lookback_window,
    )

    # Compute deterministic ETag from versionHash and request query string
    etag_raw = f"{data['versionHash']}:{request.query_string.decode('utf-8')}"
    etag = hashlib.sha256(etag_raw.encode("utf-8")).hexdigest()[:16]

    if_none_match = request.headers.get("If-None-Match")
    if if_none_match and if_none_match.strip('"') == etag:
        response = make_response("", 304)
        response.headers["ETag"] = f'"{etag}"'
        response.headers["Cache-Control"] = "public, max-age=600"
        return response

    response = make_response(jsonify(data))
    response.headers["ETag"] = f'"{etag}"'
    response.headers["Cache-Control"] = "public, max-age=600"
    return response


@bp.route("/api/items/<item_id>", methods=["GET"])
def get_item(item_id: str):
    """
    Returns current cached state plus history points for detail view.
    Never calls the upstream API.
    """
    service = get_service()
    detail = service.get_item_detail(item_id)
    if not detail:
        return jsonify({"error": f"Item '{item_id}' not found"}), 404

    return jsonify(detail)


@bp.route("/api/history/<item_id>", methods=["GET"])
def get_history(item_id: str):
    """
    Returns stored historical snapshot points for requested window.
    """
    service = get_service()
    window = request.args.get("window", "24h")
    points = service.get_history_series(item_id, window=window)
    return jsonify({"itemId": item_id, "window": window, "points": points})


@bp.route("/api/status", methods=["GET"])
def get_status():
    """
    Returns cache and refresher health information.
    """
    refresher = get_refresher()
    status_info = refresher.cache.get_status_info()
    status_info["effectiveConcurrency"] = refresher.effective_concurrency
    return jsonify(status_info)


@bp.route("/api/items/catalog", methods=["GET"])
def get_catalog():
    """
    Returns the catalog of Bazaar items that are currently known (live cache +
    previously stored).  Each entry includes the lastUpdated timestamp so the
    frontend can show per-item freshness.  Never calls the upstream API.
    """
    refresher = get_refresher()
    from app.bazaar_adapter import derive_display_name
    timestamps = refresher.cache.get_items_with_timestamps()
    catalog = [
        {
            "itemId": item_id,
            "displayName": derive_display_name(item_id),
            "lastUpdated": last_updated or None,
        }
        for item_id, last_updated in sorted(timestamps.items())
    ]
    return jsonify({"catalog": catalog})



@bp.route("/api/favorites", methods=["GET"])
def get_favorites():
    """
    Returns list of favorited item IDs stored in SQLite.
    """
    db = current_app.extensions["db"]
    favs = db.get_favorites()
    return jsonify({"favorites": favs})


@bp.route("/api/favorites", methods=["POST"])
def update_favorites():
    """
    Updates favorite state. If favorited, bumps item to front of refresher queue.
    """
    db = current_app.extensions["db"]
    refresher = get_refresher()
    data = request.get_json(silent=True) or {}

    if "itemId" in data:
        item_id = str(data["itemId"])
        is_fav = bool(data.get("isFavorite", True))
        db.set_favorite(item_id, is_fav)
        if is_fav:
            refresher.bump_favorite(item_id)
    elif "favorites" in data and isinstance(data["favorites"], list):
        fav_list = [str(i) for i in data["favorites"]]
        db.set_all_favorites(fav_list)
        for item_id in fav_list:
            refresher.bump_favorite(item_id)

    return jsonify({"favorites": db.get_favorites()})


@bp.route("/api/refresh", methods=["POST"])
def trigger_refresh():
    """
    Manually triggers a refresh cycle (non-blocking).
    """
    refresher = get_refresher()
    triggered = refresher.trigger_manual_refresh()
    return jsonify({"status": "triggered" if triggered else "already_running"})

