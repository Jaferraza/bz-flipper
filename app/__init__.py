import logging
from pathlib import Path
from typing import Optional
from flask import Flask

from app.config import Config
from app.db import Database
from app.cache import MarketCache
from app.api_client import CraftersMCClient
from app.refresher import BazaarRefresher
from app.services import DashboardService
from app.routes import bp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app(
    config_override: Optional[Config] = None,
    start_refresher: bool = True,
    api_client_override: Optional[CraftersMCClient] = None,
) -> Flask:
    """
    Application factory for CraftersMC Bazaar Flip Dashboard.
    """
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    config = config_override or Config()
    app.config["APP_CONFIG"] = config

    # 1. Initialize SQLite Database
    db = Database(config.DB_PATH)
    pruned = db.prune_old_snapshots(config.SNAPSHOT_RETENTION_DAYS)
    if pruned > 0:
        logger.info("Startup: pruned %d expired snapshots", pruned)

    # 2. Initialize in-memory cache and warm up from DB
    cache = MarketCache(ttl_seconds=config.CACHE_TTL_SECONDS)
    latest_rows = db.load_latest_states()
    if latest_rows:
        cache.warm_from_db(latest_rows)
        logger.info("Startup: warmed cache with %d items from database", len(latest_rows))

    # 3. Initialize API client & background refresher
    api_client = api_client_override or CraftersMCClient(
        base_url=config.CRAFTERSMC_API_BASE_URL,
        api_key=config.CRAFTERSMC_API_KEY,
        api_key_header=config.CRAFTERSMC_API_KEY_HEADER,
        timeout_seconds=config.UPSTREAM_TIMEOUT_SECONDS,
        max_retries=config.UPSTREAM_MAX_RETRIES,
    )

    refresher = BazaarRefresher(
        config=config,
        cache=cache,
        db=db,
        api_client=api_client,
    )

    # 4. Initialize dashboard service
    dashboard_service = DashboardService(cache=cache, db=db)

    # Attach extensions for routes to access
    app.extensions["db"] = db
    app.extensions["cache"] = cache
    app.extensions["api_client"] = api_client
    app.extensions["bazaar_refresher"] = refresher
    app.extensions["dashboard_service"] = dashboard_service

    # Register blueprint
    app.register_blueprint(bp)

    if start_refresher:
        refresher.start(initial_refresh=True)

    return app
