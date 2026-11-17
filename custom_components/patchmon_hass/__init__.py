"""The PatchMon integration (read-only patch status of PatchMon hosts)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .coordinator import ISSUE_GROUPS_WITHOUT_HOSTS, PatchMonCoordinator
from .helpers import create_client


@dataclass(slots=True)
class PatchMonRuntimeData:
    """Objects that live as long as the config entry is loaded."""

    coordinator: PatchMonCoordinator


type PatchMonConfigEntry = ConfigEntry[PatchMonRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: PatchMonConfigEntry) -> bool:
    """Set up PatchMon from a config entry."""
    coordinator = PatchMonCoordinator(hass, entry, create_client(hass, entry.data))
    # A bad token starts re-authentication right away; an unreachable server
    # or an odd answer is retried by Home Assistant.
    await coordinator.async_config_entry_first_refresh()

    # Options changes reload the entry by themselves (OptionsFlowWithReload).
    entry.runtime_data = PatchMonRuntimeData(coordinator=coordinator)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PatchMonConfigEntry) -> bool:
    """Unload a config entry (no platforms yet)."""
    return True


async def async_remove_entry(hass: HomeAssistant, entry: PatchMonConfigEntry) -> None:
    """Drop the repair issue of a removed entry."""
    ir.async_delete_issue(
        hass, DOMAIN, f"{ISSUE_GROUPS_WITHOUT_HOSTS}_{entry.entry_id}"
    )
