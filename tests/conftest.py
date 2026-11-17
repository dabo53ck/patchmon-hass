"""Shared fixtures for the PatchMon tests."""

from __future__ import annotations

import json
from collections.abc import Generator, Mapping
from enum import Enum
from pathlib import Path
from typing import Any
from unittest.mock import PropertyMock, patch

import pytest
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
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
        entry_id="01JPATCHMONTESTENTRY000000",
    )


def host_id(number: int) -> str:
    """ID of host ``number`` (1-4) in the fixtures."""
    return f"00000000-0000-4000-8000-a0000000000{number}"


def mock_details(aioclient_mock: AiohttpClientMocker) -> None:
    """Answer /system and /info of the four fixture hosts."""
    for number in range(1, 5):
        for part in ("system", "info"):
            aioclient_mock.get(
                f"{API}/hosts/{host_id(number)}/{part}",
                json=load_fixture(f"host_0{number}_{part}.json"),
            )


@pytest.fixture
def mock_hosts(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Answer GET /hosts with the host list fixture, plus the host details."""
    aioclient_mock.get(f"{API}/hosts", json=load_fixture("hosts.json"))
    mock_details(aioclient_mock)
    return aioclient_mock


@pytest.fixture
def enable_all_entities() -> Generator[None]:
    """Create entities that are disabled by default as enabled."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock,
        return_value=True,
    ):
        yield


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up a config entry."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _plain(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Attributes with enum keys and values as plain values.

    The repr of enums differs between Home Assistant versions.
    """
    return {
        str(key): value.value if isinstance(value, Enum) else value
        for key, value in attributes.items()
    }


def platform_snapshot(
    hass: HomeAssistant, entry: MockConfigEntry, domain: str
) -> dict[str, Any]:
    """Registry fields and state of every entity of ``domain``.

    Only fields that stay the same across Home Assistant versions, so the
    snapshots hold for the minimum version and the latest one.
    """
    registry = er.async_get(hass)
    result: dict[str, Any] = {}
    for entity in sorted(
        er.async_entries_for_config_entry(registry, entry.entry_id),
        key=lambda e: e.entity_id,
    ):
        if entity.domain != domain:
            continue
        state = hass.states.get(entity.entity_id)
        result[entity.entity_id] = {
            "unique_id": entity.unique_id,
            "translation_key": entity.translation_key,
            "entity_category": entity.entity_category,
            "device_class": entity.original_device_class,
            "disabled_by": entity.disabled_by,
            "state": state.state if state else None,
            "attributes": _plain(state.attributes) if state else None,
        }
    return result
