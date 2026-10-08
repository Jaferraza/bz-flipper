import json
import logging
import random
import time
from typing import Dict, Any, List, Optional
import requests

logger = logging.getLogger(__name__)


class UpstreamAPIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class RateLimitExceededError(UpstreamAPIError):
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message, status_code=429)
        self.retry_after = retry_after


class CraftersMCClient:
    """
    HTTP client for the CraftersMC SkyBlock API.
    Isolates network calls, credential injection, conditional requests,
    exponential backoff, and response validation.
    """

    def __init__(
        self,
        base_url: str = "https://api.craftersmc.net",
        api_key: str = "",
        api_key_header: str = "Authorization",
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_key_header = api_key_header
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.session = session or requests.Session()

        # Conditional request cache: url -> { 'etag': ..., 'last_modified': ..., 'data': ... }
        self._conditional_cache: Dict[str, Dict[str, Any]] = {}
        self.consecutive_429_count: int = 0

    def _inject_auth(self, headers: Dict[str, str]) -> None:
        """
        Isolated credential injection.
        Open integration point: update once authoritative credential format is specified.
        """
        if self.api_key:
            headers[self.api_key_header] = self.api_key

    def _request(self, method: str, endpoint: str) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "CraftersMC-Bazaar-Flip-Dashboard/1.0",
        }
        self._inject_auth(headers)

        # Opportunistic conditional request headers
        cached_entry = self._conditional_cache.get(url)
        if cached_entry:
            if cached_entry.get("etag"):
                headers["If-None-Match"] = cached_entry["etag"]
            if cached_entry.get("last_modified"):
                headers["If-Modified-Since"] = cached_entry["last_modified"]

        retries = 0
        backoff_delay = 1.0

        while True:
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )

                # 304 Not Modified
                if response.status_code == 304 and cached_entry:
                    self.consecutive_429_count = 0
                    return cached_entry["data"]

                # 429 Rate Limited
                if response.status_code == 429:
                    self.consecutive_429_count += 1
                    retry_after: Optional[float] = None
                    retry_after_header = response.headers.get("Retry-After")
                    if retry_after_header:
                        try:
                            retry_after = float(retry_after_header)
                        except ValueError:
                            retry_after = None

                    if retry_after is None:
                        try:
                            body = response.json()
                            if isinstance(body, dict) and "retryAfter" in body:
                                retry_after = float(body["retryAfter"])
                        except Exception:
                            pass

                    # If upstream asks for long wait (> 10s), fail fast to preserve previous cache
                    if retry_after is not None and retry_after > 10.0:
                        raise RateLimitExceededError(
                            f"Rate limit exceeded (429) for {url}, retryAfter={retry_after}s",
                            retry_after=retry_after,
                        )

                    delay = retry_after if retry_after is not None else backoff_delay
                    delay += random.uniform(0.1, 0.5)

                    if retries < self.max_retries:
                        retries += 1
                        logger.warning(
                            "Upstream 429 for %s. Backing off for %.2fs (attempt %d/%d)",
                            url,
                            delay,
                            retries,
                            self.max_retries,
                        )
                        time.sleep(delay)
                        backoff_delay *= 2.0
                        continue
                    else:
                        raise RateLimitExceededError(
                            f"Rate limit exceeded (429) for {url}", retry_after=retry_after
                        )

                # 400 Bad Request
                if response.status_code == 400:
                    raise UpstreamAPIError(f"Invalid item ID or bad request (400) for {url}", 400)

                # 401 / 403 Forbidden
                if response.status_code in (401, 403):
                    raise UpstreamAPIError(
                        f"API key missing, invalid or insufficient scope ({response.status_code}) for {url}",
                        response.status_code,
                    )

                # 404 Not Found
                if response.status_code == 404:
                    raise UpstreamAPIError(f"Data not populated yet (404) for {url}", 404)

                # 503 Service Unavailable
                if response.status_code == 503:
                    if retries < self.max_retries:
                        retries += 1
                        delay = backoff_delay + random.uniform(0.1, 0.5)
                        logger.warning("Upstream 503 for %s. Retrying in %.2fs", url, delay)
                        time.sleep(delay)
                        backoff_delay *= 2.0
                        continue
                    raise UpstreamAPIError(f"Upstream service temporarily unavailable (503) for {url}", 503)

                response.raise_for_status()

                # Successful response
                self.consecutive_429_count = 0
                data = response.json()

                # Validate response structure
                if not isinstance(data, (dict, list)):
                    raise UpstreamAPIError(f"Unexpected response format from {url}")

                # Save conditional caching metadata
                etag = response.headers.get("ETag")
                last_modified = response.headers.get("Last-Modified")
                if etag or last_modified:
                    self._conditional_cache[url] = {
                        "etag": etag,
                        "last_modified": last_modified,
                        "data": data,
                    }

                return data

            except (requests.Timeout, requests.ConnectionError) as exc:
                if retries < self.max_retries:
                    retries += 1
                    delay = backoff_delay + random.uniform(0.1, 0.5)
                    logger.warning("Network error (%s) for %s. Retrying in %.2fs", exc, url, delay)
                    time.sleep(delay)
                    backoff_delay *= 2.0
                    continue
                raise UpstreamAPIError(f"Network error accessing {url}: {exc}")

    def get_bazaar_items(self) -> List[str]:
        """
        GET /v1/resources/skyblock/bazaar/items
        Returns list of item ID strings.
        """
        data = self._request("GET", "/v1/resources/skyblock/bazaar/items")
        if isinstance(data, list):
            return [str(item) for item in data]
        if isinstance(data, dict):
            # In case wrapper like {"success": true, "items": [...]}
            if "items" in data and isinstance(data["items"], list):
                return [str(item) for item in data["items"]]
            if "data" in data and isinstance(data["data"], list):
                return [str(item) for item in data["data"]]
        raise UpstreamAPIError("Invalid items list structure returned from upstream")

    def get_bazaar_item_details(self, item_id: str) -> Dict[str, Any]:
        """
        GET /v1/skyblock/bazaar/{itemId}/details
        Returns BazaarItemReply payload.
        Validates success field.
        """
        data = self._request("GET", f"/v1/skyblock/bazaar/{item_id}/details")
        if not isinstance(data, dict):
            raise UpstreamAPIError(f"Malformed response for item {item_id}")

        if not data.get("success", False):
            raise UpstreamAPIError(
                f"Upstream returned success=false for item {item_id}: {data.get('cause', 'unknown')}"
            )

        return data
