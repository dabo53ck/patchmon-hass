"""The PatchMon integration (read-only patch status of PatchMon hosts)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import (
    PatchMonAuthError,
    PatchMonClient,
    PatchMonConnectionError,
    PatchMonUnsupportedError,
)
from .const import CONF_HOST_GROUPS, DOMAIN
from .helpers import create_client


@dataclass(slots=True)
class PatchMonRuntimeData:
    """Objects that live as long as the config entry is loaded."""

    client: PatchMonClient


type PatchMonConfigEntry = ConfigEntry[PatchMonRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: PatchMonConfigEntry) -> bool:
    """Set up PatchMon from a config entry."""
    client = create_client(hass, entry.data)
    try:
        # Probe once so a bad token starts re-authentication right away and an
        # unreachable server is retried by Home Assistant.
        await client.get_hosts(entry.options.get(CONF_HOST_GROUPS))
    except PatchMonAuthError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_failed",
            translation_placeholders={"error": err.message},
        ) from err
    except PatchMonConnectionError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err)},
        ) from err
    except PatchMonUnsupportedError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="unsupported",
            translation_placeholders={"error": str(err)},
        ) from err

    # Options changes reload the entry by themselves (OptionsFlowWithReload).
    entry.runtime_data = PatchMonRuntimeData(client=client)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PatchMonConfigEntry) -> bool:
    """Unload a config entry (no platforms yet)."""
    return True
