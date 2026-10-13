"""The collector's only network boundary. No platform writes are available."""
import math
import re
from contextlib import contextmanager
from dataclasses import dataclass

import httpx

from .config import MAX_PAGES, PAGE_SIZE, SERVER

GET_PATHS = (
    r"/v2/coworlds/summaries", r"/v2/experience-requests", r"/v2/episode-requests",
    r"/v2/episode-requests/ereq_[A-Za-z0-9-]+", r"/v2/experience-requests/xreq_[A-Za-z0-9-]+",
    r"/admin/costs/leagues", r"/admin/llm-coworld-usage",
    r"/sql/tables/(episode_llm_usage|experience_requests)/schema",
    r"/v2/league-policy-memberships", r"/v2/league-submissions",
    r"/v2/leagues/league_[A-Za-z0-9-]+/commissioner-state",
    r"/v2/divisions/div_[A-Za-z0-9-]+/(leaderboards|leaderboard/summary)",
    r"/v2/rounds/round_[A-Za-z0-9-]+/episodes",
    r"/v2/games", r"/v2/leagues", r"/v2/budgets", r"/v2/leagues/health", r"/v2/rounds",
    r"/v2/leagues/league_[A-Za-z0-9-]+/settings", r"/v2/coworlds/cow_[A-Za-z0-9-]+",
)


class ApiError(Exception):
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class Page:
    entries: list
    next_cursor: str | None
    complete: bool


class Api:
    def __init__(self, request):
        self.request = request

    def get(self, path, params=None):
        if not any(re.fullmatch(pattern, path) for pattern in GET_PATHS):
            raise ApiError("Route is not allowed")
        return self._request("GET", path, params=params)

    def _request(self, method, path, **kwargs):
        try:
            response = self.request(method, path, **kwargs)
        except httpx.HTTPError:
            raise ApiError("Network request failed") from None
        if response.status_code == 429:
            raw = response.headers.get("x-ratelimit-retry-after", response.headers.get("retry-after", "60"))
            try:
                delay = float(raw)
                if not math.isfinite(delay) or delay < 0:
                    raise ValueError
            except ValueError:
                delay = 60
            raise ApiError("API rate limit; collection deferred", max(1, delay))
        if response.status_code in (401, 403):
            raise ApiError("Login/access unavailable; use James's User login, not a player login")
        if response.status_code != 200:
            raise ApiError(f"API returned HTTP {response.status_code}")
        try:
            return response.json(), response.headers
        except ValueError:
            raise ApiError("API returned invalid JSON") from None

    def select(self, kind, ids, after=None):
        # The only POST surface accepts a named fixed SELECT, never caller-supplied SQL.
        from .sql import query
        statement = query(kind, ids, after)
        return self._request("POST", "/sql/query", json={"query": statement})[0]

    def json(self, path, params=None):
        return self.get(path, params)[0]

    def page(self, path, params=None):
        data, headers = self.get(path, params)
        if isinstance(data, list):
            rows, cursor = data, headers.get("x-next-cursor")
            # Unpaginated discovery routes are explicitly known to return whole lists.
            complete = path in ("/v2/games", "/v2/leagues") or len(rows) < (params or {}).get("limit", PAGE_SIZE)
        elif isinstance(data, dict) and isinstance(data.get("entries"), list):
            rows, cursor = data["entries"], data.get("next_cursor")
            complete = "next_cursor" in data and cursor is None
        else:
            raise ApiError("Unexpected list response shape")
        if cursor is not None and (not isinstance(cursor, str) or not cursor):
            raise ApiError("Invalid pagination cursor")
        return Page(rows, cursor, complete and not cursor)

    def pages(self, path, params=None):
        rows, cursors, ids = [], set(), set()
        params = {"limit": PAGE_SIZE, **(params or {})}
        for _ in range(MAX_PAGES):
            page = self.page(path, params)
            for row in page.entries:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in ids:
                    raise ApiError("Invalid or repeated pagination row")
                ids.add(row["id"])
            rows.extend(page.entries)
            if page.complete:
                return rows
            if not page.next_cursor or page.next_cursor in cursors:
                raise ApiError("Incomplete or repeated pagination cursor")
            cursors.add(page.next_cursor)
            params["cursor"] = page.next_cursor
        raise ApiError("Pagination exceeded the collection limit")


@contextmanager
def logged_in_api():
    # Import/login only in the collector, never while constructing a page or running tests.
    from coworld.api_client import CoworldApiClient

    CoworldApiClient.set_elevated(True)
    try:
        client = CoworldApiClient.from_login(server_url=SERVER)
    except Exception:
        raise ApiError("Login unavailable; run the project-local softmax login") from None
    with client:
        try:
            headers = client._headers()
        except RuntimeError:
            raise ApiError("Player login cannot use elevated access; select James's User login") from None
        # The SDK transport retries internally. Use its authenticated headers with a plain
        # transport so our persisted retry deadline, including x-ratelimit-retry-after, owns retries.
        with httpx.Client(base_url=SERVER + "/observatory", headers=headers,
                          timeout=httpx.Timeout(15, connect=5), follow_redirects=False) as http:
            yield Api(http.request)
