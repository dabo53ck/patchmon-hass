"""Config flow for PatchMon: setup, re-authentication, reconfiguration, options."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import probatio as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import PatchMonConfigEntry
from .api import (
    PatchMonAuthError,
    PatchMonConnectionError,
    PatchMonError,
    PatchMonSSLError,
    PatchMonUnsupportedError,
    normalize_url,
)
from .const import (
    CONF_HOST_GROUPS,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN_KEY,
    CONF_TOKEN_SECRET,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .helpers import create_client

_LOGGER = logging.getLogger(__name__)

_URL_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
_TEXT_SELECTOR = TextSelector()
_SECRET_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _credentials_schema() -> dict[vol.Marker, Any]:
    return {
        vol.Required(CONF_TOKEN_KEY): _TEXT_SELECTOR,
        vol.Required(CONF_TOKEN_SECRET): _SECRET_SELECTOR,
    }


def _error_key(err: Exception) -> str:
    """Map a client error to a translation key under config.error."""
    if isinstance(err, PatchMonAuthError):
        return err.reason.value
    if isinstance(err, PatchMonSSLError):
        return "ssl_error"
    if isinstance(err, PatchMonConnectionError):
        return "cannot_connect"
    if isinstance(err, PatchMonUnsupportedError):
        return "unsupported"
    _LOGGER.exception("Unexpected error while talking to PatchMon")
    return "unknown"


async def _async_test(hass: HomeAssistant, data: Mapping[str, Any]) -> str | None:
    """Try one read; return an error key or None when everything works."""
    try:
        await create_client(hass, data).get_hosts()
    except Exception as err:  # every failure becomes a form error
        return _error_key(err)
    return None


def _title(url: str) -> str:
    return f"PatchMon ({urlsplit(url).hostname})"


class PatchMonConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup of a PatchMon server."""

    VERSION = 1
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: PatchMonConfigEntry,
    ) -> PatchMonOptionsFlow:
        """Return the options flow."""
        return PatchMonOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the server address and an API token, then test them."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            else:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                data = {**user_input, CONF_URL: url}
                if not (error := await _async_test(self.hass, data)):
                    return self.async_create_entry(title=_title(url), data=data)
                errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_URL): _URL_SELECTOR,
                        **_credentials_schema(),
                        vol.Required(CONF_VERIFY_SSL, default=True): BooleanSelector(),
                    }
                ),
                user_input,
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication after PatchMon rejected the token."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new token key and secret."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            if not (error := await _async_test(self.hass, data)):
                return self.async_update_reload_and_abort(entry, data=data)
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(_credentials_schema()),
            description_placeholders={"url": entry.data[CONF_URL]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change address, token or TLS check without losing devices."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_URL])
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            else:
                if url != entry.unique_id and any(
                    other.unique_id == url
                    for other in self._async_current_entries(include_ignore=False)
                ):
                    return self.async_abort(reason="already_configured")
                if not user_input.get(CONF_TOKEN_SECRET):
                    # Empty secret field: keep the stored one.
                    user_input = {
                        k: v for k, v in user_input.items() if k != CONF_TOKEN_SECRET
                    }
                data = {**entry.data, **user_input, CONF_URL: url}
                if not (error := await _async_test(self.hass, data)):
                    return self.async_update_reload_and_abort(
                        entry, unique_id=url, title=_title(url), data=data
                    )
                errors["base"] = error

        suggested = {
            CONF_URL: entry.data[CONF_URL],
            CONF_TOKEN_KEY: entry.data[CONF_TOKEN_KEY],
            CONF_VERIFY_SSL: entry.data.get(CONF_VERIFY_SSL, True),
            **(user_input or {}),
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_URL): _URL_SELECTOR,
                        vol.Required(CONF_TOKEN_KEY): _TEXT_SELECTOR,
                        vol.Optional(CONF_TOKEN_SECRET): _SECRET_SELECTOR,
                        vol.Required(CONF_VERIFY_SSL): BooleanSelector(),
                    }
                ),
                suggested,
            ),
            errors=errors,
        )


class PatchMonOptionsFlow(OptionsFlowWithReload):
    """Polling interval and host group filter."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and store the options; the entry reloads afterwards."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_HOST_GROUPS: user_input.get(CONF_HOST_GROUPS, []),
                }
            )

        errors: dict[str, str] = {}
        current: list[str] = list(self.config_entry.options.get(CONF_HOST_GROUPS, []))
        groups: dict[str, str] = {}
        try:
            # Unfiltered, so every group can be chosen.
            hosts = await create_client(self.hass, self.config_entry.data).get_hosts()
        except PatchMonError as err:
            errors["base"] = _error_key(err)
        else:
            for host in hosts:
                for group in host.host_groups:
                    groups[group.id] = group.name
        # Keep selected groups that no longer exist selectable, so saving the
        # form does not fail on them.
        for group_id in current:
            groups.setdefault(group_id, group_id)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Optional(CONF_HOST_GROUPS, default=current): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=gid, label=name)
                            for gid, name in sorted(
                                groups.items(), key=lambda item: item[1].lower()
                            )
                        ],
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
