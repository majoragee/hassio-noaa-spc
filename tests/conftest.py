"""Shared pytest fixtures."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from custom_components.noaa_spc.api.spc import SpcApi
from tests.factories import alert_bundle, outlook_bundle, risk_layers


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load custom_components in every test."""
    yield


@pytest.fixture
def mock_api():
    """Patch SpcApi network methods; mutate the returned namespace in tests."""
    state = SimpleNamespace(
        outlooks=outlook_bundle(risk_layers()),
        alerts=alert_bundle(),
    )

    async def fetch_outlooks(self, previous):
        return state.outlooks

    async def fetch_alerts(self, previous):
        return state.alerts

    with (
        patch.object(SpcApi, "fetch_outlooks", fetch_outlooks),
        patch.object(SpcApi, "fetch_alerts", fetch_alerts),
    ):
        yield state
