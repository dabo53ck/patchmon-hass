"""Base entities for PatchMon hosts and the PatchMon server."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Host
from .const import DOMAIN, ENABLE_OPTIONS
from .coordinator import HostDetails, PatchMonCoordinator

if TYPE_CHECKING:
    from . import PatchMonConfigEntry


class PatchMonHostEntity(CoordinatorEntity[PatchMonCoordinator]):
    """An entity of one PatchMon host (device created by the integration)."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: PatchMonCoordinator, host_id: str, key: str
    ) -> None:
        """Bind the entity to a host; ``key`` is also the translation key."""
        super().__init__(coordinator)
        self.host_id = host_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{host_id}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, host_id)})

    def _enable_by_option(self, platform: str, key: str) -> None:
        """Take the enabled default from the options, for optional entities."""
        for option, target in ENABLE_OPTIONS.items():
            if target == (platform, key):
                options = self.coordinator.config_entry.options
                self._attr_entity_registry_enabled_default = bool(
                    options.get(option, False)
                )

    @property
    def available(self) -> bool:
        """Unavailable while PatchMon does not list the host."""
        return super().available and self.host_id in self.coordinator.data.hosts

    @property
    def host(self) -> Host:
        """The host as of the last update (only while available)."""
        return self.coordinator.data.hosts[self.host_id]


class PatchMonHostDetailEntity(PatchMonHostEntity):
    """A host entity that needs ``/system`` or ``/info``."""

    @property
    def available(self) -> bool:
        """Also unavailable while the details of the host could not be read."""
        return super().available and self.host_id in self.coordinator.data.details

    @property
    def details(self) -> HostDetails:
        """The details as of the last agent report (only while available)."""
        return self.coordinator.data.details[self.host_id]


class PatchMonServerEntity(CoordinatorEntity[PatchMonCoordinator]):
    """An entity of the PatchMon server itself (totals over all hosts)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PatchMonCoordinator, key: str) -> None:
        """Bind the entity to the server device of the config entry."""
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry_id)})


def async_add_host_entities(
    entry: PatchMonConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[str], Sequence[Entity]],
) -> None:
    """Add the entities of every host now and of new hosts later.

    A host whose device was removed (with its entities), by the integration
    or by the user, gets new entities when it comes back. The device sync
    runs first, so a returning host already has its device again.
    """
    coordinator = entry.runtime_data.coordinator
    devices = dr.async_get(coordinator.hass)
    # Host ID -> ID of its device when the entities were added.
    known: dict[str, str | None] = {}

    @callback
    def _async_add_new() -> None:
        data = coordinator.data
        if new := [host_id for host_id in data.hosts if host_id not in known]:
            for host_id in new:
                device = devices.async_get_device_by_identifier(
                    (DOMAIN, host_id), entry.entry_id
                )
                known[host_id] = device.id if device else None
            async_add_entities(
                [entity for host_id in new for entity in factory(host_id)]
            )

    @callback
    def _async_device_removed(event: Event[dr.EventDeviceRegistryUpdatedData]) -> None:
        """Removing a device removes its entities: forget its host."""
        if event.data["action"] != "remove":
            return
        for host_id, device_id in list(known.items()):
            if device_id == event.data["device_id"]:
                del known[host_id]

    _async_add_new()
    entry.async_on_unload(
        coordinator.hass.bus.async_listen(
            dr.EVENT_DEVICE_REGISTRY_UPDATED, _async_device_removed
        )
    )
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new))


@callback
def async_entities_for_option(
    hass: HomeAssistant, entry: PatchMonConfigEntry, option: str
) -> list[er.RegistryEntry]:
    """Registry entries of the optional entity behind ``option``, all hosts."""
    platform, key = ENABLE_OPTIONS[option]
    return [
        entity
        for entity in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
        if entity.domain == platform and entity.unique_id.endswith(f"_{key}")
    ]
