"""Base entities for PatchMon hosts and the PatchMon server."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Host
from .const import DOMAIN
from .coordinator import HostDetails, PatchMonCoordinator


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
