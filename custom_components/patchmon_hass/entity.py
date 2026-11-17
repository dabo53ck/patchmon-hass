"""Base entities for PatchMon hosts and the PatchMon server."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from homeassistant.core import callback
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

    A host that disappears (and whose device was removed with its entities)
    gets new entities when it comes back.
    """
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    @callback
    def _async_add_new() -> None:
        data = coordinator.data
        if data.complete:
            known.intersection_update(data.hosts)
        if new := [host_id for host_id in data.hosts if host_id not in known]:
            known.update(new)
            async_add_entities(
                [entity for host_id in new for entity in factory(host_id)]
            )

    _async_add_new()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new))
