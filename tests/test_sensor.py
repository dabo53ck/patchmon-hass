"""Tests for the PatchMon sensors."""

from __future__ import annotations

import pytest
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from syrupy.assertion import SnapshotAssertion

from .conftest import (
    API,
    host_id,
    load_fixture,
    mock_details,
    platform_snapshot,
    setup_entry,
)


@pytest.mark.usefixtures("enable_all_entities")
async def test_sensors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
) -> None:
    """All sensors of the four fixture hosts and the server totals."""
    await setup_entry(hass, mock_config_entry)

    assert platform_snapshot(hass, mock_config_entry, "sensor") == snapshot


async def test_defaults(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """Kernel and package sensors are off by default, the counters on."""
    await setup_entry(hass, mock_config_entry)

    assert hass.states.get("sensor.host_01_pending_updates") is not None
    assert hass.states.get("sensor.host_01_running_kernel") is None
    assert hass.states.get("sensor.host_01_installed_packages") is None


async def test_detail_sensors_unavailable_without_details(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Missing details only affect the detail sensors of that host."""
    aioclient_mock.get(f"{API}/hosts", json=load_fixture("hosts.json"))
    aioclient_mock.get(f"{API}/hosts/{host_id(2)}/info", status=500)
    mock_details(aioclient_mock)

    await setup_entry(hass, mock_config_entry)

    assert hass.states.get("sensor.host_02_agent_version").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.host_02_pending_updates").state == "16"
    assert hass.states.get("sensor.host_01_agent_version").state != STATE_UNAVAILABLE


async def test_new_and_returning_hosts(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """New hosts get entities; a removed host gets them again when it returns."""
    hosts = load_fixture("hosts.json")
    first, rest = hosts["hosts"][0], hosts["hosts"][1:]
    mock_hosts.clear_requests()
    mock_hosts.get(f"{API}/hosts", json={"hosts": rest})
    mock_details(mock_hosts)
    await setup_entry(hass, mock_config_entry)
    coordinator = mock_config_entry.runtime_data.coordinator
    assert hass.states.get("sensor.host_01_pending_updates") is None

    mock_hosts.clear_requests()
    mock_hosts.get(f"{API}/hosts", json={"hosts": [first, *rest]})
    mock_details(mock_hosts)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.host_01_pending_updates").state == "0"

    mock_hosts.clear_requests()
    mock_hosts.get(f"{API}/hosts", json={"hosts": rest})
    mock_details(mock_hosts)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.host_01_pending_updates") is None

    mock_hosts.clear_requests()
    mock_hosts.get(f"{API}/hosts", json={"hosts": [first, *rest]})
    mock_details(mock_hosts)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.host_01_pending_updates").state == "0"


async def test_host_missing_while_incomplete(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """Hosts of a suddenly empty list stay, but unavailable."""
    await setup_entry(hass, mock_config_entry)
    mock_hosts.clear_requests()
    mock_hosts.get(f"{API}/hosts", json={"hosts": []})
    await mock_config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get("sensor.host_01_pending_updates")
    assert state.state == STATE_UNAVAILABLE


async def test_restart_reason(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The reason shows only while a restart is needed, cut to 255 characters."""
    long_reason = load_fixture("host_01_system.json")
    long_reason["reboot_reason"] = "x" * 300
    no_reason = load_fixture("host_02_system.json")
    no_reason["reboot_reason"] = None
    aioclient_mock.get(f"{API}/hosts", json=load_fixture("hosts.json"))
    aioclient_mock.get(f"{API}/hosts/{host_id(1)}/system", json=long_reason)
    aioclient_mock.get(f"{API}/hosts/{host_id(2)}/system", json=no_reason)
    mock_details(aioclient_mock)

    await setup_entry(hass, mock_config_entry)

    assert hass.states.get("sensor.host_01_restart_reason").state == "x" * 255
    assert hass.states.get("sensor.host_02_restart_reason").state == STATE_UNKNOWN
    assert hass.states.get("sensor.host_03_restart_reason").state == STATE_UNKNOWN
