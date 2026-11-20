"""Tests for setting up and unloading the PatchMon config entry."""

from __future__ import annotations

import logging

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.patchmon_hass import async_remove_config_entry_device
from custom_components.patchmon_hass.const import CONF_AREA, CONF_HOST_GROUPS, DOMAIN

from .conftest import API, ENTRY_DATA, URL, host_id, load_fixture, mock_details


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


def _device(
    registry: dr.DeviceRegistry, entry: MockConfigEntry, ident: str
) -> dr.DeviceEntry | None:
    return registry.async_get_device_by_identifier((DOMAIN, ident), entry.entry_id)


async def test_devices(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
) -> None:
    """One service device for the server, one device per host behind it."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    server = _device(device_registry, mock_config_entry, mock_config_entry.entry_id)
    assert server is not None
    assert server.name == "PatchMon"
    assert server.entry_type is dr.DeviceEntryType.SERVICE
    assert server.configuration_url == URL

    host = _device(device_registry, mock_config_entry, host_id(1))
    assert host is not None
    assert host.name == "Host 01"
    assert host.model == "Debian GNU/Linux"
    assert host.sw_version == "13 (trixie)"
    assert host.via_device_id == server.id
    assert host.configuration_url == f"{URL}/hosts/{host_id(1)}"
    assert (
        len(
            dr.async_entries_for_config_entry(
                device_registry, mock_config_entry.entry_id
            )
        )
        == 5
    )


async def test_devices_follow_patchmon(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Renames are taken over, user names kept, deleted hosts removed."""
    caplog.set_level(logging.DEBUG, logger="custom_components.patchmon_hass")
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = mock_config_entry.runtime_data.coordinator
    host_2 = _device(device_registry, mock_config_entry, host_id(2))
    assert host_2 is not None
    device_registry.async_update_device(host_2.id, name_by_user="My server")

    hosts = load_fixture("hosts.json")
    hosts["hosts"][0]["friendly_name"] = "Renamed"
    hosts["hosts"][1]["friendly_name"] = "Also renamed"
    del hosts["hosts"][3]
    hosts["total"] = 3
    mock_hosts.clear_requests()
    mock_hosts.get(f"{API}/hosts", json=hosts)
    mock_details(mock_hosts)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    host_1 = _device(device_registry, mock_config_entry, host_id(1))
    assert host_1 is not None
    assert host_1.name == "Renamed"
    host_2 = _device(device_registry, mock_config_entry, host_id(2))
    assert host_2 is not None
    assert host_2.name_by_user == "My server"
    assert _device(device_registry, mock_config_entry, host_id(4)) is None
    assert _device(device_registry, mock_config_entry, mock_config_entry.entry_id)
    assert "Added device PatchMon" in caplog.text
    assert "PatchMon no longer lists it" in caplog.text


async def _refresh_with(
    hass: HomeAssistant, entry: MockConfigEntry, mock: AiohttpClientMocker, hosts: dict
) -> None:
    mock.clear_requests()
    mock.get(f"{API}/hosts", json=hosts)
    mock_details(mock)
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


async def test_new_devices_get_area(
    hass: HomeAssistant,
    mock_hosts: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    area_registry: ar.AreaRegistry,
) -> None:
    """New devices go to the area of the options; moved devices stay."""
    area = area_registry.async_create("Server room")
    office = area_registry.async_create("Office")
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=URL,
        data=dict(ENTRY_DATA),
        options={CONF_AREA: area.id},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert len(devices) == 5
    assert {device.area_id for device in devices} == {area.id}

    host_2 = _device(device_registry, entry, host_id(2))
    assert host_2 is not None
    device_registry.async_update_device(host_2.id, area_id=office.id)
    await _refresh_with(hass, entry, mock_hosts, load_fixture("hosts.json"))

    host_2 = _device(device_registry, entry, host_id(2))
    assert host_2 is not None
    assert host_2.area_id == office.id


async def test_area_only_for_devices_created_later(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    area_registry: ar.AreaRegistry,
) -> None:
    """Setting the area later leaves existing devices alone."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    area = area_registry.async_create("Server room")
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_AREA: area.id}
    )
    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    host_1 = _device(device_registry, mock_config_entry, host_id(1))
    assert host_1 is not None
    assert host_1.area_id is None

    # Host 4 is deleted in PatchMon and enrolled again: it is a new device.
    hosts = load_fixture("hosts.json")
    without_4 = {"hosts": hosts["hosts"][:3]}
    await _refresh_with(hass, mock_config_entry, mock_hosts, without_4)
    assert _device(device_registry, mock_config_entry, host_id(4)) is None
    await _refresh_with(hass, mock_config_entry, mock_hosts, hosts)

    host_4 = _device(device_registry, mock_config_entry, host_id(4))
    assert host_4 is not None
    assert host_4.area_id == area.id


async def test_deleted_area_is_ignored(
    hass: HomeAssistant,
    mock_hosts: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
) -> None:
    """An area deleted in Home Assistant is not assigned."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=URL,
        data=dict(ENTRY_DATA),
        options={CONF_AREA: "deleted_area"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    assert devices
    assert {device.area_id for device in devices} == {None}


async def test_devices_kept_while_list_incomplete(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A suddenly empty host list removes no device."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_hosts.clear_requests()
    mock_hosts.get(f"{API}/hosts", json={"hosts": [], "total": 0})
    await mock_config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert _device(device_registry, mock_config_entry, host_id(1)) is not None


async def test_devices_kept_when_empty_after_restart(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
) -> None:
    """An empty list on the first update after a restart removes no device."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)

    mock_hosts.clear_requests()
    mock_hosts.get(f"{API}/hosts", json={"hosts": [], "total": 0})
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert not mock_config_entry.runtime_data.coordinator.data.complete
    assert _device(device_registry, mock_config_entry, host_id(1)) is not None


async def test_deleted_device_gets_entities_back(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """A device the user deleted gets its entities again when the host returns."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # The list is suddenly empty: devices stay, the user deletes one.
    await _refresh_with(hass, mock_config_entry, mock_hosts, {"hosts": []})
    device = _device(device_registry, mock_config_entry, host_id(1))
    assert device is not None
    assert await async_remove_config_entry_device(hass, mock_config_entry, device)
    device_registry.async_remove_device(device.id)
    await hass.async_block_till_done()

    await _refresh_with(hass, mock_config_entry, mock_hosts, load_fixture("hosts.json"))
    await hass.async_block_till_done()

    device = _device(device_registry, mock_config_entry, host_id(1))
    assert device is not None
    entities = er.async_entries_for_device(entity_registry, device.id)
    assert entities
    # Hosts that kept their device did not get a second set of entities.
    other = _device(device_registry, mock_config_entry, host_id(2))
    assert other is not None
    assert len(er.async_entries_for_device(entity_registry, other.id)) == len(entities)
    assert hass.states.get(entities[0].entity_id) is not None or entities[0].disabled


async def test_remove_device_while_not_loaded(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Without a host list, host devices may go; the server device stays."""
    aioclient_mock.get(f"{API}/hosts", exc=TimeoutError())
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    entry_id = mock_config_entry.entry_id
    server = device_registry.async_get_or_create(
        config_entry_id=entry_id, identifiers={(DOMAIN, entry_id)}
    )
    host = device_registry.async_get_or_create(
        config_entry_id=entry_id, identifiers={(DOMAIN, host_id(1))}
    )

    assert not await async_remove_config_entry_device(hass, mock_config_entry, server)
    assert await async_remove_config_entry_device(hass, mock_config_entry, host)


async def test_remove_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Only devices of hosts PatchMon no longer lists can be deleted."""
    assert await async_setup_component(hass, "config", {})
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    entry_id = mock_config_entry.entry_id

    server = _device(device_registry, mock_config_entry, entry_id)
    listed = _device(device_registry, mock_config_entry, host_id(1))
    stale = device_registry.async_get_or_create(
        config_entry_id=entry_id, identifiers={(DOMAIN, "gone")}
    )
    assert server is not None
    assert listed is not None

    assert not await async_remove_config_entry_device(hass, mock_config_entry, server)
    assert not await async_remove_config_entry_device(hass, mock_config_entry, listed)
    assert await async_remove_config_entry_device(hass, mock_config_entry, stale)


async def test_restored_entities_follow_switch(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    entity_registry: er.EntityRegistry,
) -> None:
    """Entities restored on a new setup are enabled when the switch is on."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    unique_id = f"{host_id(1)}_updates"
    entity_id = entity_registry.async_get_entity_id("update", DOMAIN, unique_id)
    assert entity_id is not None
    # Rename it, so a restore is recognisable by the entity ID.
    entity_registry.async_update_entity(entity_id, new_entity_id="update.restored")
    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert entity_registry.async_get("update.restored") is None

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=URL,
        data=dict(ENTRY_DATA),
        options={"enable_update_entity": True},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    restored = entity_registry.async_get("update.restored")
    assert restored is not None
    assert restored.disabled_by is None
