"""Binary sensors per host: restart required and agent reporting."""

from __future__ import annotations

from typing import Any

# Moved to .const in HA 2026.10 and re-exported without __all__; the
# package import works on every supported version.
from homeassistant.components.binary_sensor import (  # type: ignore[attr-defined,unused-ignore]
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PatchMonConfigEntry
from .coordinator import PatchMonCoordinator
from .entity import PatchMonHostEntity, async_add_host_entities

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PatchMonConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the binary sensors of every (new) host."""
    coordinator = entry.runtime_data.coordinator

    def _host_entities(host_id: str) -> list[BinarySensorEntity]:
        return [
            RestartRequiredSensor(coordinator, host_id),
            ReportingSensor(coordinator, host_id),
        ]

    async_add_host_entities(entry, async_add_entities, _host_entities)


class RestartRequiredSensor(PatchMonHostEntity, BinarySensorEntity):
    """On while PatchMon reports that the host needs a restart.

    The reason is a sensor of its own (``restart_reason``).
    """

    def __init__(self, coordinator: PatchMonCoordinator, host_id: str) -> None:
        """Bind to a host."""
        super().__init__(coordinator, host_id, "restart_required")

    @property
    def is_on(self) -> bool | None:
        """Restart flag from the host list."""
        return self.host.needs_reboot


class ReportingSensor(PatchMonHostEntity, BinarySensorEntity):
    """On while the agent reports in time (PatchMon's own thresholds)."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: PatchMonCoordinator, host_id: str) -> None:
        """Bind to a host."""
        super().__init__(coordinator, host_id, "reporting")

    @property
    def is_on(self) -> bool | None:
        """``reporting`` is on; ``overdue`` and ``stale`` are off."""
        state = self.host.reporting_state
        return None if state is None else state == "reporting"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """PatchMon's reporting state: reporting, overdue or stale."""
        state = self.host.reporting_state
        return None if state is None else {"reporting_state": state}
