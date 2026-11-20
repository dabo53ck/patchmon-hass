"""Tests for the PatchMon diagnostics."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
    get_diagnostics_for_device,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator
from syrupy.assertion import SnapshotAssertion
from syrupy.filters import props

from custom_components.patchmon_hass.const import DOMAIN

from .conftest import API, ENTRY_DATA, ENTRY_ID, URL, host_id, setup_entry

# Must never appear in a download.
SECRETS = (
    URL,
    "patchmon.example",
    ENTRY_DATA["token_key"],
    ENTRY_DATA["token_secret"],
    "192.0.2.",
    "host-01",
    "Host 01",
)


def _assert_redacted(result: dict[str, object]) -> None:
    text = json.dumps(result)
    for secret in SECRETS:
        assert secret not in text, secret


def _device(hass: HomeAssistant, ident: str) -> dr.DeviceEntry:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, ident), ENTRY_ID
    )
    assert device is not None
    return device


async def test_entry_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
) -> None:
    """Settings, update state and all hosts, without secrets or names."""
    await setup_entry(hass, mock_config_entry)

    result = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )

    _assert_redacted(result)
    assert result == snapshot(exclude=props("fetched_at"))


async def test_device_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
) -> None:
    """A host device shows its host; the server device shows everything."""
    await setup_entry(hass, mock_config_entry)

    host = await get_diagnostics_for_device(
        hass, hass_client, mock_config_entry, _device(hass, host_id(1))
    )
    _assert_redacted(host)
    assert host == snapshot(exclude=props("fetched_at"))

    server = await get_diagnostics_for_device(
        hass, hass_client, mock_config_entry, _device(hass, mock_config_entry.entry_id)
    )
    assert server == await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )


async def test_diagnostics_after_failed_update(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """Errors appear by type only: their text can hold the server address."""
    await setup_entry(hass, mock_config_entry)
    mock_hosts.clear_requests()
    mock_hosts.get(f"{API}/hosts", status=503)
    await mock_config_entry.runtime_data.coordinator.async_refresh()

    result = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )

    _assert_redacted(result)
    assert result["coordinator"]["last_exception"] == {
        "type": "UpdateFailed",
        "translation_key": "cannot_connect",
        "cause": "PatchMonConnectionError",
    }
