"""Small helpers shared by setup and the config flow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PatchMonClient
from .const import CONF_TOKEN_KEY, CONF_TOKEN_SECRET


def create_client(hass: HomeAssistant, data: Mapping[str, Any]) -> PatchMonClient:
    """Create an API client from config entry data, on HA's shared session."""
    return PatchMonClient(
        async_get_clientsession(hass, verify_ssl=data.get(CONF_VERIFY_SSL, True)),
        data[CONF_URL],
        data[CONF_TOKEN_KEY],
        data[CONF_TOKEN_SECRET],
    )
