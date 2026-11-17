"""Tests for the PatchMon binary sensors."""

from __future__ import annotations

from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from syrupy.assertion import SnapshotAssertion

from .conftest import API, load_fixture, mock_details, platform_snapshot, setup_entry


async def test_binary_sensors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
) -> None:
    """Restart flag with reason, and the reporting state of every host."""
    await setup_entry(hass, mock_config_entry)

    assert platform_snapshot(hass, mock_config_entry, "binary_sensor") == snapshot


async def test_old_server_and_overdue(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Missing fields give unknown; overdue is off with the state attribute."""
    hosts = load_fixture("hosts.json")
    del hosts["hosts"][0]["reporting_state"]
    del hosts["hosts"][0]["needs_reboot"]
    hosts["hosts"][1]["reporting_state"] = "overdue"
    aioclient_mock.get(f"{API}/hosts", json=hosts)
    mock_details(aioclient_mock)

    await setup_entry(hass, mock_config_entry)

    assert hass.states.get("binary_sensor.host_01_reporting").state == STATE_UNKNOWN
    assert (
        hass.states.get("binary_sensor.host_01_restart_required").state == STATE_UNKNOWN
    )
    overdue = hass.states.get("binary_sensor.host_02_reporting")
    assert overdue.state == "off"
    assert overdue.attributes["reporting_state"] == "overdue"
