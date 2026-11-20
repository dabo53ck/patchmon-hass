"""The PatchMon integration (read-only patch status of PatchMon hosts)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_URL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import CONF_AREA, DOMAIN, ENABLE_OPTIONS
from .coordinator import (
    ISSUE_GROUPS_WITHOUT_HOSTS,
    ISSUE_UNSUPPORTED,
    PatchMonCoordinator,
)
from .entity import async_entities_for_option
from .helpers import create_client
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.UPDATE]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(slots=True)
class PatchMonRuntimeData:
    """Objects that live as long as the config entry is loaded."""

    coordinator: PatchMonCoordinator


type PatchMonConfigEntry = ConfigEntry[PatchMonRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions; they report clearly when no entry is loaded."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PatchMonConfigEntry) -> bool:
    """Set up PatchMon from a config entry."""
    coordinator = PatchMonCoordinator(hass, entry, create_client(hass, entry.data))
    # A bad token starts re-authentication right away; an unreachable server
    # or an odd answer is retried by Home Assistant.
    await coordinator.async_config_entry_first_refresh()

    # Options changes reload the entry by themselves (OptionsFlowWithReload).
    entry.runtime_data = PatchMonRuntimeData(coordinator=coordinator)

    server = _async_get_or_create_device(
        hass,
        entry,
        identifiers={(DOMAIN, entry.entry_id)},
        name="PatchMon",
        manufacturer="PatchMon",
        entry_type=dr.DeviceEntryType.SERVICE,
        configuration_url=entry.data[CONF_URL],
    )

    @callback
    def _async_sync() -> None:
        _async_sync_devices(hass, entry, coordinator, server.id)

    _async_sync()
    entry.async_on_unload(coordinator.async_add_listener(_async_sync))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_enable_switched_on(hass, entry)
    return True


@callback
def _async_enable_switched_on(hass: HomeAssistant, entry: PatchMonConfigEntry) -> None:
    """Enable optional entities that the integration disabled, if switched on.

    Home Assistant restores entities of a removed entry (kept 30 days) with
    their old disabled state, which can contradict the switches chosen when
    the entry is set up again. Entities disabled by the user stay disabled.
    Home Assistant reloads the entry by itself after enabling.
    """
    registry = er.async_get(hass)
    for option in ENABLE_OPTIONS:
        if not entry.options.get(option, False):
            continue
        for entity in async_entities_for_option(hass, entry, option):
            if entity.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
                registry.async_update_entity(entity.entity_id, disabled_by=None)


@callback
def _async_get_or_create_device(
    hass: HomeAssistant, entry: PatchMonConfigEntry, **device: Any
) -> dr.DeviceEntry:
    """Create or update a device; a new one goes to the area from the options.

    Only devices without an area get it, so devices the user moved, or
    restored devices that had an area, stay where they are.
    """
    registry = dr.async_get(hass)
    (identifier,) = device["identifiers"]
    is_new = registry.async_get_device_by_identifier(identifier, entry.entry_id) is None
    entry_device = registry.async_get_or_create(
        config_entry_id=entry.entry_id, **device
    )
    if is_new:
        _LOGGER.debug("Added device %s", entry_device.name)
    area_id = entry.options.get(CONF_AREA)
    if (
        is_new
        and area_id
        and entry_device.area_id is None
        and ar.async_get(hass).async_get_area(area_id) is not None
    ):
        return registry.async_update_device(entry_device.id, area_id=area_id) or (
            entry_device
        )
    return entry_device


@callback
def _async_sync_devices(
    hass: HomeAssistant,
    entry: PatchMonConfigEntry,
    coordinator: PatchMonCoordinator,
    server_device_id: str,
) -> None:
    """Create or update a device per host; remove devices of deleted hosts.

    Names set by the user stay (``name_by_user`` wins over ``name``).
    Nothing is removed while the host list may be incomplete.
    """
    registry = dr.async_get(hass)
    data = coordinator.data
    url = entry.data[CONF_URL]
    for host in data.hosts.values():
        _async_get_or_create_device(
            hass,
            entry,
            identifiers={(DOMAIN, host.id)},
            name=host.friendly_name,
            model=host.os_type,
            sw_version=host.os_version,
            via_device_id=server_device_id,
            configuration_url=f"{url}/hosts/{host.id}",
        )
    if not data.complete:
        _LOGGER.debug("Host list may be incomplete; no device is removed")
        return
    keep = {entry.entry_id, *data.hosts}
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if not any(
            domain == DOMAIN and ident in keep for domain, ident in device.identifiers
        ):
            # A device belongs to this entry only; removing it also removes
            # its entities.
            _LOGGER.debug(
                "Removing device %s: PatchMon no longer lists it", device.name
            )
            registry.async_remove_device(device.id)


async def async_unload_entry(hass: HomeAssistant, entry: PatchMonConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: PatchMonConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow deleting a host device only while PatchMon does not list it.

    The server device stays. While the entry is not loaded (for example the
    server is unreachable) there is no host list, so host devices may go.
    """
    hosts = (
        entry.runtime_data.coordinator.data.hosts
        if entry.state is ConfigEntryState.LOADED
        else {}
    )
    return not any(
        domain == DOMAIN and (ident == entry.entry_id or ident in hosts)
        for domain, ident in device.identifiers
    )


async def async_remove_entry(hass: HomeAssistant, entry: PatchMonConfigEntry) -> None:
    """Drop the repair issues of a removed entry."""
    for issue in (ISSUE_GROUPS_WITHOUT_HOSTS, ISSUE_UNSUPPORTED):
        ir.async_delete_issue(hass, DOMAIN, f"{issue}_{entry.entry_id}")
