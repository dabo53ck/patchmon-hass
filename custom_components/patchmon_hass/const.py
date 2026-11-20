"""Constants for the PatchMon integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "patchmon_hass"

CONF_TOKEN_KEY: Final = "token_key"
CONF_TOKEN_SECRET: Final = "token_secret"

# Options
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_HOST_GROUPS: Final = "host_groups"
# Names of the filter groups when they were chosen, for messages about
# groups that have no hosts any more (their name is not in the host list).
CONF_HOST_GROUP_NAMES: Final = "host_group_names"
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

# Update status of a host (sensor states and filter values of get_hosts).
UPDATE_STATES: Final = ["up_to_date", "updates_pending", "security_required"]

# Actions
SERVICE_GET_HOSTS: Final = "get_hosts"
SERVICE_GET_PACKAGES: Final = "get_packages"
SERVICE_REFRESH: Final = "refresh"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_DEVICE_ID: Final = "device_id"
ATTR_UPDATE_STATUS: Final = "update_status"
ATTR_RESTART_REQUIRED: Final = "restart_required"
ATTR_REPORTING: Final = "reporting"
ATTR_UPDATES_ONLY: Final = "updates_only"
ATTR_SECURITY_ONLY: Final = "security_only"
ATTR_LIMIT: Final = "limit"
ATTR_INCLUDE_DESCRIPTIONS: Final = "include_descriptions"
DEFAULT_PACKAGE_LIMIT: Final = 50
MAX_PACKAGE_LIMIT: Final = 1000
