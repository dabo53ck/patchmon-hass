"""Update entity per host (disabled by default, read-only).

PatchMon has no version number for a host, so the versions are labels:
installed is always ``current``; latest is ``current`` without pending
updates, otherwise ``16 updates (1 security)`` or ``16 updates``.
The package list is shown as release notes; nothing can be installed.
"""

from __future__ import annotations

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PatchMonConfigEntry
from .api import Package, PatchMonError
from .const import DOMAIN
from .coordinator import PatchMonCoordinator
from .entity import PatchMonHostEntity, async_add_host_entities

PARALLEL_UPDATES = 0

CURRENT = "current"
MAX_PACKAGES = 50


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PatchMonConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the update entity of every (new) host."""
    coordinator = entry.runtime_data.coordinator
    async_add_host_entities(
        entry,
        async_add_entities,
        lambda host_id: [PatchMonUpdate(coordinator, host_id)],
    )


def _latest_version(updates: int | None, security: int | None) -> str | None:
    if updates is None:
        return None
    if not updates:
        return CURRENT
    label = f"{updates} update" if updates == 1 else f"{updates} updates"
    return f"{label} ({security} security)" if security else label


def _release_notes(packages: list[Package]) -> str:
    """Markdown list, security updates first, at most ``MAX_PACKAGES`` lines."""
    ordered = sorted(packages, key=lambda p: (not p.is_security_update, p.name))
    lines = []
    for package in ordered[:MAX_PACKAGES]:
        versions = (
            f"{package.current_version or '?'} → {package.available_version or '?'}"
        )
        security = " (security)" if package.is_security_update else ""
        lines.append(f"- **{package.name}** {versions}{security}")
    if (more := len(ordered) - MAX_PACKAGES) > 0:
        lines.append(f"- … {more} more")
    return "\n".join(lines)


class PatchMonUpdate(PatchMonHostEntity, UpdateEntity):
    """Pending package updates of one host as an update entity."""

    _attr_entity_registry_enabled_default = False
    _attr_supported_features = UpdateEntityFeature.RELEASE_NOTES
    _attr_installed_version = CURRENT

    def __init__(self, coordinator: PatchMonCoordinator, host_id: str) -> None:
        """Bind to a host."""
        super().__init__(coordinator, host_id, "updates")

    @property
    def latest_version(self) -> str | None:
        """Label with the number of pending (security) updates."""
        return _latest_version(
            self.host.updates_count, self.host.security_updates_count
        )

    async def async_release_notes(self) -> str | None:
        """Read the packages with updates when the dialog opens."""
        try:
            packages = await self.coordinator.client.get_host_packages(self.host_id)
        except PatchMonError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="packages_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        return _release_notes(packages)
