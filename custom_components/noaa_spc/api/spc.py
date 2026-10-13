"""High-level SPC fetching. Must not import Home Assistant."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from .client import SpcApiError, SpcClient
from .mds import parse_md_feed, parse_md_page
from .models import MesoscaleDiscussion, OutlookLayer, TextProduct, Watch
from .outlooks import parse_layer
from .products import (
    IMAGE_PATHS,
    LAYER_PATHS,
    MD_FEED_PATH,
    SPC_BASE,
    TEXT_PATHS,
    WATCH_FEED_PATH,
)
from .text import parse_text_product
from .watches import parse_watch_feed

_LOGGER = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class OutlookBundle:
    layers: Mapping[str, OutlookLayer]
    texts: Mapping[str, TextProduct]
    images: Mapping[str, bytes]
    updated: Mapping[str, datetime]


@dataclass(frozen=True)
class AlertBundle:
    watches: tuple[Watch, ...]
    mds: tuple[MesoscaleDiscussion, ...]
    watches_updated: datetime | None
    mds_updated: datetime | None


class SpcApi:
    def __init__(self, client: SpcClient, *, max_concurrency: int = 4) -> None:
        self._client = client
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._logged: set[str] = set()
        self._md_cache: dict[int, MesoscaleDiscussion] = {}

    def _failed(self, key: str, err: Exception) -> None:
        message = f"{key}: {err}"
        if message not in self._logged:
            self._logged.add(message)
            _LOGGER.warning("Failed to update SPC product %s", message)

    def _succeeded(self, key: str) -> None:
        self._logged = {m for m in self._logged if not m.startswith(f"{key}: ")}

    async def _get(self, url: str, **kwargs):
        async with self._semaphore:
            return await self._client.fetch(url, **kwargs)

    async def fetch_outlooks(self, previous: OutlookBundle | None) -> OutlookBundle:
        layers = dict(previous.layers) if previous else {}
        texts = dict(previous.texts) if previous else {}
        images = dict(previous.images) if previous else {}
        updated = dict(previous.updated) if previous else {}

        async def layer(key: str, path: str) -> None:
            name = f"layer:{key}"
            try:
                fetched = await self._get(SPC_BASE + path)
                if fetched.changed or key not in layers:
                    layers[key] = parse_layer(json.loads(fetched.body))
            except SpcApiError as err:
                self._failed(name, err)
                return
            except ValueError as err:
                self._client.invalidate(SPC_BASE + path)
                self._failed(name, err)
                return
            updated[name] = _now()
            self._succeeded(name)

        async def text(key: str, path: str) -> None:
            name = f"text:{key}"
            try:
                fetched = await self._get(SPC_BASE + path)
                if fetched.changed or key not in texts:
                    texts[key] = parse_text_product(
                        fetched.body.decode("utf-8", "replace")
                    )
            except SpcApiError as err:
                self._failed(name, err)
                return
            except ValueError as err:
                self._client.invalidate(SPC_BASE + path)
                self._failed(name, err)
                return
            updated[name] = _now()
            self._succeeded(name)

        async def image(key: str, path: str) -> None:
            name = f"image:{key}"
            try:
                fetched = await self._get(SPC_BASE + path)
            except SpcApiError as err:
                self._failed(name, err)
                return
            if fetched.changed or key not in images:
                images[key] = fetched.body
            updated[name] = _now()
            self._succeeded(name)

        await asyncio.gather(
            *(layer(k, p) for k, p in LAYER_PATHS.items()),
            *(text(k, p) for k, p in TEXT_PATHS.items()),
            *(image(k, p) for k, (p, _) in IMAGE_PATHS.items()),
        )
        return OutlookBundle(layers, texts, images, updated)

    async def fetch_alerts(self, previous: AlertBundle | None) -> AlertBundle:
        watches = previous.watches if previous else ()
        mds = previous.mds if previous else ()
        watches_updated = previous.watches_updated if previous else None
        mds_updated = previous.mds_updated if previous else None

        try:
            fetched = await self._get(SPC_BASE + WATCH_FEED_PATH)
            watches = parse_watch_feed(fetched.body)
        except (SpcApiError, ValueError) as err:
            self._failed("watches", err)
        else:
            watches_updated = _now()
            self._succeeded("watches")

        try:
            fetched = await self._get(SPC_BASE + MD_FEED_PATH)
            entries = parse_md_feed(fetched.body)
        except (SpcApiError, ValueError) as err:
            self._failed("mds", err)
        else:
            current: list[MesoscaleDiscussion] = []
            for number, url in entries:
                md = self._md_cache.get(number)
                if md is None:
                    try:
                        page = await self._get(url, conditional=False)
                        md = parse_md_page(page.body.decode("utf-8", "replace"), url)
                    except (SpcApiError, ValueError) as err:
                        self._failed(f"md:{number}", err)
                        md = next((m for m in mds if m.number == number), None)
                        if md is not None:
                            current.append(md)
                        continue
                    self._md_cache[number] = md
                    self._succeeded(f"md:{number}")
                current.append(md)
            active = {number for number, _ in entries}
            self._md_cache = {n: m for n, m in self._md_cache.items() if n in active}
            mds = tuple(current)
            mds_updated = _now()
            self._succeeded("mds")

        return AlertBundle(watches, mds, watches_updated, mds_updated)
