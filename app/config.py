import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    CRAFTERSMC_API_BASE_URL: str = os.getenv(
        "CRAFTERSMC_API_BASE_URL", "https://api.craftersmc.net"
    ).rstrip("/")
    CRAFTERSMC_API_KEY: str = os.getenv("CRAFTERSMC_API_KEY", "")
    CRAFTERSMC_API_KEY_HEADER: str = os.getenv(
        "CRAFTERSMC_API_KEY_HEADER", "X-API-Key"
    )

    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "5000"))
    DEBUG: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")

    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "600"))
    STATIC_METADATA_TTL_SECONDS: int = int(
        os.getenv("STATIC_METADATA_TTL_SECONDS", "43200")
    )
    UPSTREAM_MAX_CONCURRENCY: int = int(os.getenv("UPSTREAM_MAX_CONCURRENCY", "4"))
    UPSTREAM_TIMEOUT_SECONDS: float = float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "15"))
    UPSTREAM_MAX_RETRIES: int = int(os.getenv("UPSTREAM_MAX_RETRIES", "3"))
    REFRESH_JITTER_SECONDS: float = float(os.getenv("REFRESH_JITTER_SECONDS", "0"))
    UPSTREAM_REQUEST_DELAY_SECONDS: float = float(
        os.getenv("UPSTREAM_REQUEST_DELAY_SECONDS", "7.5")
    )

    BAZAAR_TAX_RATE: float = float(os.getenv("BAZAAR_TAX_RATE", "0.01"))
    ENABLE_HEURISTIC_PROFIT_PER_HOUR: bool = os.getenv(
        "ENABLE_HEURISTIC_PROFIT_PER_HOUR", "false"
    ).lower() in ("true", "1", "yes")
    HEURISTIC_VOLUME_WINDOW_HOURS: float = float(
        os.getenv("HEURISTIC_VOLUME_WINDOW_HOURS", "1.0")
    )

    DB_PATH: str = os.getenv("DB_PATH", str(BASE_DIR / "data" / "bazaar.db"))
    SNAPSHOT_RETENTION_DAYS: int = int(os.getenv("SNAPSHOT_RETENTION_DAYS", "7"))

    # Optional local mock toggle for offline/test running
    USE_MOCK_API: bool = os.getenv("USE_MOCK_API", "false").lower() in (
        "true",
        "1",
        "yes",
    )
