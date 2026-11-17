"""Tests for setting up and unloading the PatchMon config entry."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.patchmon_hass.const import CONF_HOST_GROUPS, DOMAIN

from .conftest import API


async def test_setup_and_unload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """The entry loads after one successful read and unloads cleanly."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    coordinator = mock_config_entry.runtime_data.coordinator
    assert len(coordinator.data.hosts) == 4
    assert len(coordinator.data.details) == 4
    # Host list plus /system and /info of every host
    assert mock_hosts.call_count == 1 + 4 * 2

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_uses_host_group_option(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The host group filter from the options is sent to PatchMon."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="http://patchmon.example:3000",
        data={
            "url": "http://patchmon.example:3000",
            "token_key": "k",
            "token_secret": "s",
            "verify_ssl": True,
        },
        options={CONF_HOST_GROUPS: ["g1"]},
    )
    entry.add_to_hass(hass)
    aioclient_mock.get(f"{API}/hosts", json={"hosts": [], "total": 0})

    assert await hass.config_entries.async_setup(entry.entry_id)

    _, url, _, _ = aioclient_mock.mock_calls[0]
    assert url.query["hostgroup"] == "g1"


async def test_setup_auth_failed_starts_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A rejected token puts the entry into error and starts re-authentication."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{API}/hosts", status=401, json={"error": "API key has expired"}
    )

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH
    assert (
        mock_config_entry.reason
        == "PatchMon rejected the API token: API key has expired"
    )


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"exc": TimeoutError()}, "Could not reach the PatchMon server: TimeoutError"),
        ({"status": 503, "text": ""}, "Could not reach the PatchMon server: HTTP 503"),
        (
            {"status": 200, "text": "<html></html>"},
            "Unexpected answer from the PatchMon server: Unexpected answer (HTTP 200)",
        ),
    ],
)
async def test_setup_retry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    kwargs: dict[str, object],
    reason: str,
) -> None:
    """Unreachable servers and odd answers are retried later."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{API}/hosts", **kwargs)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert mock_config_entry.reason == reason
