"""Data update coordinator for PatchMon: host list plus per-host details."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    Host,
    HostInfo,
    HostSystem,
    PatchMonAuthError,
    PatchMonClient,
    PatchMonConnectionError,
    PatchMonError,
    PatchMonNotFoundError,
)
from .const import (
    CONF_HOST_GROUPS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

if TYPE_CHECKING:
    from . import PatchMonConfigEntry

_LOGGER = logging.getLogger(__name__)

# Details only change when the agent reports; re-read them at least this often.
DETAILS_MAX_AGE = timedelta(hours=6)
ISSUE_GROUPS_WITHOUT_HOSTS = "host_groups_without_hosts"


@dataclass(frozen=True, slots=True)
class HostDetails:
    """``/system`` and ``/info`` of one host, as of one agent report."""

    system: HostSystem
    info: HostInfo
    fetched_at: datetime
    last_update: datetime | None


@dataclass(slots=True)
class PatchMonData:
    """What the entities read."""

    hosts: dict[str, Host]
    # Hosts whose details could not be read in the last attempt are missing.
    details: dict[str, HostDetails]
    # False when the host list may be incomplete (a filtered group has no
    # hosts, or the list is suddenly empty): then nothing must be removed.
    complete: bool = True
    groups_without_hosts: tuple[str, ...] = field(default=())


def _update_state(host: Host) -> Host:
    """Fill ``update_state`` like PatchMon does, for servers without it."""
    if host.update_state is not None or host.updates_count is None:
        return host
    if host.security_updates_count:
        state = "security_required"
    elif host.updates_count:
        state = "updates_pending"
    else:
        state = "up_to_date"
    return replace(host, update_state=state)


class PatchMonCoordinator(DataUpdateCoordinator[PatchMonData]):
    """Poll the host list; read details only when a host reported again."""

    config_entry: PatchMonConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: PatchMonConfigEntry,
        client: PatchMonClient,
    ) -> None:
        """Set up polling with the interval from the options."""
        minutes = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=minutes),
            always_update=False,
        )
        self.client = client
        self._host_groups: list[str] = list(entry.options.get(CONF_HOST_GROUPS, []))
        self._group_names: dict[str, str] = {}

    async def _async_update_data(self) -> PatchMonData:
        try:
            hosts = await self.client.get_hosts(self._host_groups or None)
        except PatchMonAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
                translation_placeholders={"error": err.message},
            ) from err
        except PatchMonConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err
        except PatchMonError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="unsupported",
                translation_placeholders={"error": str(err)},
            ) from err

        by_id = {host.id: _update_state(host) for host in hosts}
        for host in hosts:
            self._group_names.update({g.id: g.name for g in host.host_groups})

        missing = self._groups_without_hosts(hosts)
        suddenly_empty = not by_id and self.data is not None and bool(self.data.hosts)
        if suddenly_empty:
            _LOGGER.warning(
                "PatchMon returned no hosts; keeping the known devices for now"
            )

        details = await self._async_update_details(by_id)
        return PatchMonData(
            hosts=by_id,
            details=details,
            complete=not missing and not suddenly_empty,
            groups_without_hosts=missing,
        )

    def _groups_without_hosts(self, hosts: list[Host]) -> tuple[str, ...]:
        """Return filter groups no host belongs to, and raise a repair for them.

        PatchMon answers a filter on a deleted group ID with an empty list
        instead of an error, so its hosts would look deleted. A host of a
        filtered group is always part of the answer, so a group without any
        host in the answer is either deleted or empty.
        """
        present = {group.id for host in hosts for group in host.host_groups}
        missing = tuple(g for g in self._host_groups if g not in present)
        issue_id = f"{ISSUE_GROUPS_WITHOUT_HOSTS}_{self.config_entry.entry_id}"
        if missing:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_GROUPS_WITHOUT_HOSTS,
                translation_placeholders={
                    "title": self.config_entry.title,
                    "groups": ", ".join(self._group_names.get(g, g) for g in missing),
                },
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        return missing

    async def _async_update_details(
        self, hosts: dict[str, Host]
    ) -> dict[str, HostDetails]:
        """Keep fresh details, re-read the others (the client limits parallelism).

        Hosts deleted in the meantime are dropped from ``hosts``.
        """
        old = self.data.details if self.data is not None else {}
        now = dt_util.utcnow()
        details: dict[str, HostDetails] = {}
        stale: list[Host] = []
        for host_id, host in hosts.items():
            known = old.get(host_id)
            if (
                known is not None
                and known.last_update == host.last_update
                and now - known.fetched_at < DETAILS_MAX_AGE
            ):
                details[host_id] = known
            else:
                stale.append(host)

        results = await asyncio.gather(
            *(self._async_fetch_details(host, now) for host in stale),
            return_exceptions=True,
        )
        for host, result in zip(stale, results, strict=True):
            if isinstance(result, HostDetails):
                details[host.id] = result
            elif isinstance(result, PatchMonAuthError):
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN,
                    translation_key="auth_failed",
                    translation_placeholders={"error": result.message},
                ) from result
            elif isinstance(result, PatchMonNotFoundError):
                # Deleted between the list and the details request.
                del hosts[host.id]
            elif isinstance(result, PatchMonError):
                _LOGGER.debug(
                    "Could not read details of %s: %s", host.friendly_name, result
                )
            else:
                raise result
        return details

    async def _async_fetch_details(self, host: Host, now: datetime) -> HostDetails:
        system = await self.client.get_host_system(host.id)
        info = await self.client.get_host_info(host.id)
        return HostDetails(
            system=system, info=info, fetched_at=now, last_update=host.last_update
        )
