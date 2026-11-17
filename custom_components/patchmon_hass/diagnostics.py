"""Diagnostics for PatchMon: per entry and per device.

The server address, the token, host names, IP addresses and machine IDs
are redacted. Errors are reported by type only, because their texts can
contain the server address.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from . import PatchMonConfigEntry
from .const import CONF_TOKEN_KEY, CONF_TOKEN_SECRET, DOMAIN
from .coordinator import PatchMonCoordinator

TO_REDACT = {
    CONF_URL,
    CONF_TOKEN_KEY,
    CONF_TOKEN_SECRET,
    "friendly_name",
    "hostname",
    "ip",
    "machine_id",
}


def _plain(value: Any) -> Any:
    """Datetimes as ISO strings, recursively."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


def _error(err: BaseException | None) -> dict[str, Any] | None:
    if err is None:
        return None
    key = err.translation_key if isinstance(err, HomeAssistantError) else None
    cause = err.__cause__
    return {
        "type": type(err).__name__,
        "translation_key": key,
        "cause": type(cause).__name__ if cause else None,
    }


def _host(coordinator: PatchMonCoordinator, host_id: str) -> dict[str, Any]:
    data = coordinator.data
    host = data.hosts.get(host_id)
    details = data.details.get(host_id)
    return async_redact_data(
        _plain(
            {
                "id": host_id,
                "listed": host is not None,
                "host": asdict(host) if host else None,
                "details": asdict(details) if details else None,
            }
        ),
        TO_REDACT,
    )


def _entry(entry: PatchMonConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    interval = coordinator.update_interval
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": _error(coordinator.last_exception),
            "update_interval_seconds": interval.total_seconds() if interval else None,
            "hosts": len(data.hosts),
            "hosts_with_details": len(data.details),
            "complete": data.complete,
            "groups_without_hosts": list(data.groups_without_hosts),
        },
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PatchMonConfigEntry
) -> dict[str, Any]:
    """Settings, update state and every host."""
    coordinator = entry.runtime_data.coordinator
    return {
        **_entry(entry),
        "hosts": [
            _host(coordinator, host_id) for host_id in sorted(coordinator.data.hosts)
        ],
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: PatchMonConfigEntry, device: dr.DeviceEntry
) -> dict[str, Any]:
    """Settings and update state, plus the host of the device."""
    host_ids = [
        ident
        for domain, ident in device.identifiers
        if domain == DOMAIN and ident != entry.entry_id
    ]
    if not host_ids:
        return await async_get_config_entry_diagnostics(hass, entry)
    return {**_entry(entry), "host": _host(entry.runtime_data.coordinator, host_ids[0])}
