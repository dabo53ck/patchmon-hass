"""Constants for the PatchMon integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "patchmon_hass"

CONF_TOKEN_KEY: Final = "token_key"
CONF_TOKEN_SECRET: Final = "token_secret"

# Options
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_HOST_GROUPS: Final = "host_groups"
# Area for devices created from now on (area ID); existing devices keep theirs.
CONF_AREA: Final = "area"
# Section of the options form with one switch per optional entity.
CONF_OPTIONAL_ENTITIES: Final = "optional_entities"
# Option -> (platform, entity key) of the host entities that are disabled by
# default. Switching an option on or off enables or disables that entity of
# every host; new hosts get it as the option says.
ENABLE_OPTIONS: Final[dict[str, tuple[str, str]]] = {
    "enable_update_entity": ("update", "updates"),
    "enable_running_kernel": ("sensor", "running_kernel"),
    "enable_installed_kernel": ("sensor", "installed_kernel"),
    "enable_installed_packages": ("sensor", "installed_packages"),
}

DEFAULT_SCAN_INTERVAL: Final = 5  # minutes
MIN_SCAN_INTERVAL: Final = 1
MAX_SCAN_INTERVAL: Final = 60
