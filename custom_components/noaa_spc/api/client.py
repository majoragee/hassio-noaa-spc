"""HTTP client with conditional GET caching. Must not import Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass

import aiohttp

from .products import USER_AGENT


class SpcApiError(Exception):
    """A request to SPC failed."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Fetched:
    body: bytes
    changed: bool


class SpcClient:
    def __init__(
        self, session: aiohttp.ClientSession, *, timeout: float = 30.0
    ) -> None:
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        # url -> (etag, last_modified, body)
        self._cache: dict[str, tuple[str | None, str | None, bytes]] = {}

    async def fetch(
        self, url: str, *, accept: str | None = None, conditional: bool = True
    ) -> Fetched:
        headers = {"User-Agent": USER_AGENT}
        if accept:
            headers["Accept"] = accept
        cached = self._cache.get(url) if conditional else None
        if cached:
            etag, last_modified, _ = cached
            if etag:
                headers["If-None-Match"] = etag
            if last_modified:
                headers["If-Modified-Since"] = last_modified
        try:
            async with self._session.get(
                url, headers=headers, timeout=self._timeout
            ) as resp:
                if resp.status == 304 and cached:
                    return Fetched(cached[2], changed=False)
                if resp.status >= 300:
                    raise SpcApiError(f"HTTP {resp.status} from {url}", resp.status)
                body = await resp.read()
                etag = resp.headers.get("ETag")
                last_modified = resp.headers.get("Last-Modified")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SpcApiError(f"{url}: {err!r}") from err
        changed = cached is None or cached[2] != body
        if conditional and (etag or last_modified):
            self._cache[url] = (etag, last_modified, body)
        return Fetched(body, changed=changed)
