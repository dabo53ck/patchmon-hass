"""Shared fixtures for the PatchMon tests."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.patchmon_hass.const import (
    CONF_TOKEN_KEY,
    CONF_TOKEN_SECRET,
    DOMAIN,
)

FIXTURES = Path(__file__).parent / "fixtures"

URL = "http://patchmon.example:3000"
API = f"{URL}/api/v1/api"
HOST_01 = "00000000-0000-4000-8000-a00000000001"

ENTRY_DATA = {
    CONF_URL: URL,
    CONF_TOKEN_KEY: "patchmon_test_key",
    CONF_TOKEN_SECRET: "test-secret",
    CONF_VERIFY_SSL: True,
}


def load_fixture(name: str) -> Any:
    """Return a JSON fixture (anonymised real PatchMon 2.1.8 answers)."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Enable loading of the custom component in every test."""
    yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A config entry for the test server."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="PatchMon (patchmon.example)",
        unique_id=URL,
        data=dict(ENTRY_DATA),
    )


@pytest.fixture
def mock_hosts(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Answer GET /hosts with the host list fixture."""
    aioclient_mock.get(f"{API}/hosts", json=load_fixture("hosts.json"))
    return aioclient_mock
