"""Constants for the PatchMon integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "patchmon_hass"

CONF_TOKEN_KEY: Final = "token_key"
CONF_TOKEN_SECRET: Final = "token_secret"

# Options
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_HOST_GROUPS: Final = "host_groups"

DEFAULT_SCAN_INTERVAL: Final = 5  # minutes
MIN_SCAN_INTERVAL: Final = 1
MAX_SCAN_INTERVAL: Final = 60
