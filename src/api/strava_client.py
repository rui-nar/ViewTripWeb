"""Strava API client for GetTracks."""

import threading
import requests
import time
from collections import deque
from typing import Any, Dict, Optional

from src.config.settings import Config
from src.auth.oauth import OAuth2Session
from src.auth.token_store import TokenStore
from src.exceptions.errors import APIError, AuthenticationError, TokenError


class RateLimiter:
    """Sliding-window rate limiter: max 100 requests per 15 minutes.

    Strava enforces 100 req/15min and 1000 req/day. This class enforces
    the per-15-min limit. The lock is held during sleep to prevent two
    concurrent threads from double-booking the same slot.
    """

    WINDOW_SECONDS: int = 900  # 15 minutes
    MAX_REQUESTS: int = 100

    def __init__(self) -> None:
        self._timestamps: deque = deque()
        self._lock: threading.Lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a request slot is available, then claim it."""
        with self._lock:
            now = time.monotonic()
            cutoff = now - self.WINDOW_SECONDS

            # Discard timestamps outside the current window
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()

            if len(self._timestamps) >= self.MAX_REQUESTS:
                # Wait until the oldest timestamp falls outside the window
                sleep_for = self.WINDOW_SECONDS - (now - self._timestamps[0])
                if sleep_for > 0:
                    time.sleep(sleep_for)
                # Re-prune after sleeping
                now = time.monotonic()
                cutoff = now - self.WINDOW_SECONDS
                while self._timestamps and self._timestamps[0] < cutoff:
                    self._timestamps.popleft()

            self._timestamps.append(time.monotonic())

    @property
    def current_usage(self) -> int:
        """Return number of requests made in the current window."""
        with self._lock:
            now = time.monotonic()
            cutoff = now - self.WINDOW_SECONDS
            return sum(1 for t in self._timestamps if t >= cutoff)


class StravaAPI:
    """Client for interacting with the Strava API."""

    BASE_URL = "https://www.strava.com/api/v3"
    MAX_RETRIES: int = 3

    def __init__(self, config: Config, user_id: str = "default"):
        self.config = config
        self.user_id = user_id
        self.oauth = OAuth2Session(config)
        self.token_data = TokenStore.load_token(user_id) or {}
        self._rate_limiter = RateLimiter()

    def _ensure_token(self) -> None:
        """Ensure access token is valid, refresh if needed."""
        if not self.token_data:
            raise AuthenticationError("No token data available. Please authenticate with Strava.")

        # simple expiration check
        if self.token_data.get("expires_at", 0) < time.time():
            try:
                self.token_data = self.oauth.refresh_token(self.token_data.get("refresh_token"))
                TokenStore.save_token(self.user_id, self.token_data)
            except TokenError as e:
                # Token refresh failed - clear the invalid token
                self.clear_token()
                raise AuthenticationError(
                    "Token refresh failed. Please re-authenticate with Strava. "
                    f"Error: {str(e)}"
                )

    def clear_token(self) -> None:
        """Clear stored token data."""
        self.token_data = {}
        try:
            TokenStore.delete_token(self.user_id)
        except Exception:
            pass  # Token might not exist or can't be deleted

    def set_token(self, token_data: Dict[str, Any]) -> None:
        """Store initial token data."""
        self.token_data = token_data
        TokenStore.save_token(self.user_id, token_data)

    def request(self, method: str, path: str, max_retries: int = MAX_RETRIES, **kwargs) -> Dict[str, Any]:
        """Make an authenticated request with rate limiting and retry logic.

        Retry behaviour:
          - HTTP 401: attempt one token refresh then retry; raise AuthenticationError on failure
          - HTTP 429: wait Retry-After (or 60s) then retry
          - HTTP 5xx: exponential backoff (1s, 2s, 4s) then retry
          - HTTP 4xx (not 401/429): raise APIError immediately, no retry
        """
        self._ensure_token()
        headers = {"Authorization": f"Bearer {self.token_data['access_token']}"}
        url = f"{self.BASE_URL}{path}"

        _refreshed = False
        last_error: Optional[str] = None
        for attempt in range(max_retries):
            self._rate_limiter.acquire()
            resp = requests.request(method, url, headers=headers, **kwargs)

            if resp.status_code < 400:
                return resp.json()

            if resp.status_code == 401:
                if not _refreshed:
                    # Token may have been revoked or expired early — try refresh once
                    _refreshed = True
                    try:
                        self.token_data = self.oauth.refresh_token(
                            self.token_data.get("refresh_token")
                        )
                        TokenStore.save_token(self.user_id, self.token_data)
                        headers = {"Authorization": f"Bearer {self.token_data['access_token']}"}
                        continue   # retry with new token
                    except Exception:
                        pass
                self.clear_token()
                raise AuthenticationError(
                    "Strava access token is invalid or expired. "
                    "Please re-authenticate via Add track → From Strava…"
                )

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                time.sleep(max(retry_after, 60))
                last_error = "Rate limited (429)"
                continue

            if resp.status_code >= 500:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                last_error = f"Server error {resp.status_code}: {resp.text}"
                continue

            # Other 4xx: not retryable
            raise APIError(f"Strava API error {resp.status_code}: {resp.text}")

        raise APIError(f"Request failed after {max_retries} attempts. Last error: {last_error}")

    def get_activities(self, **params) -> Dict[str, Any]:
        """Fetch list of activities."""
        return self.request("GET", "/athlete/activities", params=params)

    def get_activity_streams(self, activity_id: int) -> Dict[str, Any]:
        """Fetch GPS streams (latlng, altitude, time, distance) for a single activity."""
        return self.request(
            "GET",
            f"/activities/{activity_id}/streams",
            params={"keys": "latlng,altitude,time,distance", "key_by_type": "true"},
        )

    @property
    def remaining_requests(self) -> int:
        """Requests still available in the current 15-min rate-limit window."""
        return RateLimiter.MAX_REQUESTS - self._rate_limiter.current_usage
