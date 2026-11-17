"""Sensors: update counters and status per host, totals for the server."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import PatchMonConfigEntry
from .api import Host
from .coordinator import HostDetails, PatchMonCoordinator, PatchMonData
from .entity import (
    PatchMonHostDetailEntity,
    PatchMonHostEntity,
    PatchMonServerEntity,
    async_add_host_entities,
)

PARALLEL_UPDATES = 0

UPDATE_STATES = ["up_to_date", "updates_pending", "security_required"]
# Longest state Home Assistant accepts.
MAX_STATE_LENGTH = 255


@dataclass(frozen=True, kw_only=True)
class HostSensorDescription(SensorEntityDescription):
    """A sensor fed from the host list."""

    value_fn: Callable[[Host], StateType | datetime]


@dataclass(frozen=True, kw_only=True)
class DetailSensorDescription(SensorEntityDescription):
    """A sensor fed from ``/system`` or ``/info`` (and the host list)."""

    value_fn: Callable[[Host, HostDetails], StateType | datetime]


@dataclass(frozen=True, kw_only=True)
class ServerSensorDescription(SensorEntityDescription):
    """A total over all hosts of the entry."""

    value_fn: Callable[[PatchMonData], int]


HOST_SENSORS: tuple[HostSensorDescription, ...] = (
    HostSensorDescription(
        key="updates",
        translation_key="updates",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda host: host.updates_count,
    ),
    HostSensorDescription(
        key="security_updates",
        translation_key="security_updates",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda host: host.security_updates_count,
    ),
    HostSensorDescription(
        key="update_status",
        translation_key="update_status",
        device_class=SensorDeviceClass.ENUM,
        options=UPDATE_STATES,
        value_fn=lambda host: (
            host.update_state if host.update_state in UPDATE_STATES else None
        ),
    ),
    HostSensorDescription(
        key="last_check_in",
        translation_key="last_check_in",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda host: host.last_update,
    ),
    HostSensorDescription(
        key="installed_packages",
        translation_key="installed_packages",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda host: host.total_packages,
    ),
)


def _restart_reason(host: Host, details: HostDetails) -> str | None:
    """PatchMon's reason while a restart is needed; unknown otherwise.

    The flag comes from the host list, which is newer than the details.
    """
    if not host.needs_reboot or not (reason := details.system.reboot_reason):
        return None
    return reason[:MAX_STATE_LENGTH]


DETAIL_SENSORS: tuple[DetailSensorDescription, ...] = (
    DetailSensorDescription(
        key="restart_reason",
        translation_key="restart_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_restart_reason,
    ),
    DetailSensorDescription(
        key="agent_version",
        translation_key="agent_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda _, details: details.info.agent_version,
    ),
    DetailSensorDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda _, details: details.system.boot_time,
    ),
    DetailSensorDescription(
        key="running_kernel",
        translation_key="running_kernel",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda _, details: details.system.kernel_version,
    ),
    DetailSensorDescription(
        key="installed_kernel",
        translation_key="installed_kernel",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda _, details: details.system.installed_kernel_version,
    ),
)


def _count(data: PatchMonData, test: Callable[[Host], bool]) -> int:
    return sum(1 for host in data.hosts.values() if test(host))


SERVER_SENSORS: tuple[ServerSensorDescription, ...] = (
    ServerSensorDescription(
        key="hosts",
        translation_key="hosts",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: len(data.hosts),
    ),
    ServerSensorDescription(
        key="hosts_with_updates",
        translation_key="hosts_with_updates",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _count(data, lambda host: bool(host.updates_count)),
    ),
    ServerSensorDescription(
        key="hosts_with_security_updates",
        translation_key="hosts_with_security_updates",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _count(
            data, lambda host: bool(host.security_updates_count)
        ),
    ),
    ServerSensorDescription(
        key="hosts_requiring_restart",
        translation_key="hosts_requiring_restart",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _count(data, lambda host: host.needs_reboot is True),
    ),
    ServerSensorDescription(
        key="hosts_not_reporting",
        translation_key="hosts_not_reporting",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _count(
            data, lambda host: host.reporting_state in ("overdue", "stale")
        ),
    ),
    ServerSensorDescription(
        key="total_updates",
        translation_key="total_updates",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: sum(h.updates_count or 0 for h in data.hosts.values()),
    ),
    ServerSensorDescription(
        key="total_security_updates",
        translation_key="total_security_updates",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: sum(
            h.security_updates_count or 0 for h in data.hosts.values()
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PatchMonConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the server totals and the sensors of every (new) host."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        PatchMonServerSensor(coordinator, description) for description in SERVER_SENSORS
    )

    def _host_entities(host_id: str) -> list[SensorEntity]:
        return [
            *(PatchMonHostSensor(coordinator, host_id, d) for d in HOST_SENSORS),
            *(PatchMonDetailSensor(coordinator, host_id, d) for d in DETAIL_SENSORS),
        ]

    async_add_host_entities(entry, async_add_entities, _host_entities)


class PatchMonHostSensor(PatchMonHostEntity, SensorEntity):
    """A sensor fed from the host list."""

    entity_description: HostSensorDescription

    def __init__(
        self,
        coordinator: PatchMonCoordinator,
        host_id: str,
        description: HostSensorDescription,
    ) -> None:
        """Bind the description to a host."""
        super().__init__(coordinator, host_id, description.key)
        self.entity_description = description
        self._enable_by_option(Platform.SENSOR, description.key)

    @property
    def native_value(self) -> StateType | datetime:
        """Value from the host list."""
        return self.entity_description.value_fn(self.host)


class PatchMonDetailSensor(PatchMonHostDetailEntity, SensorEntity):
    """A sensor fed from the host details."""

    entity_description: DetailSensorDescription

    def __init__(
        self,
        coordinator: PatchMonCoordinator,
        host_id: str,
        description: DetailSensorDescription,
    ) -> None:
        """Bind the description to a host."""
        super().__init__(coordinator, host_id, description.key)
        self.entity_description = description
        self._enable_by_option(Platform.SENSOR, description.key)

    @property
    def native_value(self) -> StateType | datetime:
        """Value from the host details."""
        return self.entity_description.value_fn(self.host, self.details)


class PatchMonServerSensor(PatchMonServerEntity, SensorEntity):
    """A total over all hosts."""

    entity_description: ServerSensorDescription

    def __init__(
        self, coordinator: PatchMonCoordinator, description: ServerSensorDescription
    ) -> None:
        """Bind the description to the server device."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int:
        """Total over the hosts of the last update."""
        return self.entity_description.value_fn(self.coordinator.data)
