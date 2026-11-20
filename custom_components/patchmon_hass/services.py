"""Actions of the PatchMon integration.

All of them only read: ``get_hosts`` answers from the last update,
``get_packages`` asks PatchMon for the packages of one host, ``refresh``
reads the host list (and details) now. None of them changes anything in
PatchMon, and ``refresh`` does not make the agents report.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

import probatio as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.util.json import JsonValueType

from .api import (
    Host,
    Package,
    PatchMonAuthError,
    PatchMonConnectionError,
    PatchMonError,
    PatchMonNotFoundError,
)
from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DEVICE_ID,
    ATTR_INCLUDE_DESCRIPTIONS,
    ATTR_LIMIT,
    ATTR_REPORTING,
    ATTR_RESTART_REQUIRED,
    ATTR_SECURITY_ONLY,
    ATTR_UPDATE_STATUS,
    ATTR_UPDATES_ONLY,
    DEFAULT_PACKAGE_LIMIT,
    DOMAIN,
    MAX_PACKAGE_LIMIT,
    SERVICE_GET_HOSTS,
    SERVICE_GET_PACKAGES,
    SERVICE_REFRESH,
    UPDATE_STATES,
)
from .coordinator import PatchMonData

if TYPE_CHECKING:
    from . import PatchMonConfigEntry

NOT_REPORTING = ("overdue", "stale")

GET_HOSTS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_UPDATE_STATUS): vol.All(
            cv.ensure_list, [vol.In(UPDATE_STATES)]
        ),
        vol.Optional(ATTR_RESTART_REQUIRED): cv.boolean,
        vol.Optional(ATTR_REPORTING): cv.boolean,
    }
)

GET_PACKAGES_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_UPDATES_ONLY, default=True): cv.boolean,
        vol.Optional(ATTR_SECURITY_ONLY, default=False): cv.boolean,
        vol.Optional(ATTR_LIMIT, default=DEFAULT_PACKAGE_LIMIT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_PACKAGE_LIMIT)
        ),
        vol.Optional(ATTR_INCLUDE_DESCRIPTIONS, default=False): cv.boolean,
    }
)

REFRESH_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string])}
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions (once, when the integration is set up)."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_HOSTS,
        _async_get_hosts,
        schema=GET_HOSTS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PACKAGES,
        _async_get_packages,
        schema=GET_PACKAGES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, _async_refresh, schema=REFRESH_SCHEMA
    )


def _not_loaded() -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key="not_loaded"
    )


def _loaded_entries(
    hass: HomeAssistant, entry_id: str | None
) -> list[PatchMonConfigEntry]:
    """The loaded entries, or the one given; raise if there is none."""
    if entry_id is not None:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_found",
                translation_placeholders={"entry_id": entry_id},
            )
        entries = [entry]
    else:
        entries = hass.config_entries.async_entries(DOMAIN)
    loaded = [e for e in entries if e.state is ConfigEntryState.LOADED]
    if not loaded:
        raise _not_loaded()
    return loaded


def _resolve_device(
    hass: HomeAssistant, device_id: str
) -> tuple[PatchMonConfigEntry, str | None]:
    """Entry and host ID of a PatchMon device; the host ID is None for the server."""
    device = dr.async_get(hass).async_get(device_id)
    entry = (
        hass.config_entries.async_get_entry(device.config_entry_id)
        if device is not None
        else None
    )
    if device is not None and entry is not None and entry.domain == DOMAIN:
        if entry.state is not ConfigEntryState.LOADED:
            raise _not_loaded()
        for domain, ident in device.identifiers:
            if domain == DOMAIN:
                return entry, None if ident == entry.entry_id else ident
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="device_not_found",
        translation_placeholders={"device_id": device_id},
    )


def _device_name(
    hass: HomeAssistant, entry: PatchMonConfigEntry, host: Host
) -> tuple[str | None, str]:
    """Device ID and the name shown in Home Assistant (the user's name wins)."""
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, host.id), entry.entry_id
    )
    if device is None:  # Only between an update and the device sync.
        return None, host.friendly_name  # pragma: no cover
    return device.id, device.name_by_user or device.name or host.friendly_name


def _matches(host: Host, filters: dict[str, Any]) -> bool:
    """Whether a host passes every filter given (unknown values never do)."""
    if (states := filters.get(ATTR_UPDATE_STATUS)) and host.update_state not in states:
        return False
    if (
        restart := filters.get(ATTR_RESTART_REQUIRED)
    ) is not None and host.needs_reboot is not restart:
        return False
    if (reporting := filters.get(ATTR_REPORTING)) is not None:
        state = host.reporting_state
        if state is None or (state == "reporting") is not reporting:
            return False
    return True


def _host_summary(
    hass: HomeAssistant, entry: PatchMonConfigEntry, data: PatchMonData, host: Host
) -> dict[str, Any]:
    device_id, name = _device_name(hass, entry, host)
    details = data.details.get(host.id)
    reason = details.system.reboot_reason if details and host.needs_reboot else None
    return {
        "name": name,
        "patchmon_name": host.friendly_name,
        "device_id": device_id,
        "server": entry.title,
        "os": " ".join(p for p in (host.os_type, host.os_version) if p) or None,
        "update_status": host.update_state,
        "updates": host.updates_count,
        "security_updates": host.security_updates_count,
        "restart_required": host.needs_reboot,
        "restart_reason": reason,
        "reporting_state": host.reporting_state,
        "last_check_in": host.last_update.isoformat() if host.last_update else None,
        "agent_version": details.info.agent_version if details else None,
    }


async def _async_get_hosts(call: ServiceCall) -> ServiceResponse:
    """Hosts of the last update, optionally filtered; no request to PatchMon."""
    hass = call.hass
    hosts = [
        _host_summary(hass, entry, entry.runtime_data.coordinator.data, host)
        for entry in _loaded_entries(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        for host in entry.runtime_data.coordinator.data.hosts.values()
        if _matches(host, call.data)
    ]
    hosts.sort(key=lambda h: (h["name"].casefold(), h["server"]))
    return {"count": len(hosts), "hosts": cast(list[JsonValueType], hosts)}


def _package(package: Package, descriptions: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": package.name,
        "current_version": package.current_version,
        "available_version": package.available_version,
        "needs_update": package.needs_update,
        "security_update": package.is_security_update,
    }
    if descriptions:
        result["description"] = package.description
    return result


async def _async_get_packages(call: ServiceCall) -> ServiceResponse:
    """Packages of one host, read from PatchMon now."""
    hass = call.hass
    entry, host_id = _resolve_device(hass, call.data[ATTR_DEVICE_ID])
    if host_id is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="not_a_host"
        )
    updates_only = call.data[ATTR_UPDATES_ONLY]
    security_only = call.data[ATTR_SECURITY_ONLY]
    coordinator = entry.runtime_data.coordinator
    try:
        packages = await coordinator.client.get_host_packages(
            host_id, updates_only=updates_only or security_only
        )
    except PatchMonAuthError as err:
        entry.async_start_reauth(hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="auth_failed",
            translation_placeholders={"error": err.message},
        ) from err
    except PatchMonNotFoundError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="host_not_found"
        ) from err
    except PatchMonConnectionError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err)},
        ) from err
    except PatchMonError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="unsupported",
            translation_placeholders={"error": str(err)},
        ) from err

    selected = sorted(
        (
            p
            for p in packages
            if (p.needs_update or not updates_only)
            and (p.is_security_update or not security_only)
        ),
        key=lambda p: (not p.is_security_update, p.name),
    )
    limit = call.data[ATTR_LIMIT]
    host = coordinator.data.hosts.get(host_id)
    device = dr.async_get(hass).async_get(call.data[ATTR_DEVICE_ID])
    name = (device and (device.name_by_user or device.name)) or (
        host.friendly_name if host else host_id
    )
    descriptions = call.data[ATTR_INCLUDE_DESCRIPTIONS]
    return {
        "name": name,
        "device_id": call.data[ATTR_DEVICE_ID],
        "total": len(selected),
        "truncated": len(selected) > limit,
        "packages": [_package(p, descriptions) for p in selected[:limit]],
    }


async def _async_refresh(call: ServiceCall) -> None:
    """Read the host list and details now (agents are not asked to report)."""
    hass = call.hass
    targets: dict[str, tuple[PatchMonConfigEntry, set[str] | None]] = {}
    if device_ids := call.data.get(ATTR_DEVICE_ID):
        for device_id in device_ids:
            entry, host_id = _resolve_device(hass, device_id)
            _, hosts = targets.setdefault(entry.entry_id, (entry, set()))
            if host_id is None or hosts is None:
                targets[entry.entry_id] = (entry, None)
            else:
                hosts.add(host_id)
    else:
        targets = {e.entry_id: (e, None) for e in _loaded_entries(hass, None)}

    results = await asyncio.gather(
        *(
            entry.runtime_data.coordinator.async_refresh_now(hosts)
            for entry, hosts in targets.values()
        ),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, BaseException):
            raise result
