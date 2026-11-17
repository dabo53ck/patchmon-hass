"""Tests for the PatchMon config, re-auth, reconfigure and options flows."""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import patch

import pytest
import yarl
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.patchmon_hass.api import PatchMonSSLError
from custom_components.patchmon_hass.const import (
    CONF_AREA,
    CONF_HOST_GROUPS,
    CONF_OPTIONAL_ENTITIES,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN_KEY,
    CONF_TOKEN_SECRET,
    DOMAIN,
    ENABLE_OPTIONS,
)

from .conftest import API, ENTRY_DATA, URL, host_id, load_fixture, setup_entry

USER_INPUT = {
    CONF_URL: "http://PatchMon.example:3000/api/v1/api/",
    CONF_TOKEN_KEY: "patchmon_test_key",
    CONF_TOKEN_SECRET: "test-secret",
    CONF_VERIFY_SSL: True,
}

# (mock kwargs for GET /hosts, expected error key)
ERROR_CASES = [
    ({"exc": TimeoutError()}, "cannot_connect"),
    ({"status": 502, "text": ""}, "cannot_connect"),
    ({"status": 401, "json": load_fixture("error_401.json")}, "invalid_credentials"),
    ({"status": 401, "json": {"error": "API key is disabled"}}, "token_disabled"),
    ({"status": 401, "json": {"error": "API key has expired"}}, "token_expired"),
    ({"status": 403, "json": {"error": "IP address not allowed"}}, "ip_not_allowed"),
    (
        {"status": 403, "json": {"error": "Access denied", "message": "no host:get"}},
        "missing_permission",
    ),
    ({"status": 200, "text": "<!doctype html>"}, "unsupported"),
]


async def _start_user_flow(hass: HomeAssistant) -> dict[str, Any]:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


async def test_user_flow(hass: HomeAssistant, mock_hosts: AiohttpClientMocker) -> None:
    """A working server and token create an entry with the normalised address."""
    result = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "PatchMon (patchmon.example)"
    assert result["data"] == ENTRY_DATA
    assert result["options"] == {}
    assert result["result"].unique_id == URL


async def test_user_flow_with_area(
    hass: HomeAssistant,
    mock_hosts: AiohttpClientMocker,
    area_registry: ar.AreaRegistry,
) -> None:
    """The chosen area is stored as an option, not with the credentials."""
    area = area_registry.async_create("Server room")
    result = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_AREA: area.id}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == ENTRY_DATA
    assert result["options"] == {CONF_AREA: area.id}


@pytest.mark.parametrize(("mock_kwargs", "error"), ERROR_CASES)
async def test_user_flow_errors_then_recover(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_kwargs: dict[str, Any],
    error: str,
) -> None:
    """Every failure is shown on the form, and the user can retry."""
    result = await _start_user_flow(hass)
    aioclient_mock.get(f"{API}/hosts", **mock_kwargs)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API}/hosts", json=load_fixture("hosts.json"))
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_ssl_error(hass: HomeAssistant) -> None:
    """Certificate problems get their own hint."""
    result = await _start_user_flow(hass)

    with patch(
        "custom_components.patchmon_hass.api.PatchMonClient.get_hosts",
        side_effect=PatchMonSSLError("bad cert"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_URL: "https://patchmon.example"}
        )

    assert result["errors"] == {"base": "ssl_error"}


async def test_user_flow_unknown_error(hass: HomeAssistant) -> None:
    """A bug in the client is logged and shown as unknown error."""
    result = await _start_user_flow(hass)

    with patch(
        "custom_components.patchmon_hass.api.PatchMonClient.get_hosts",
        side_effect=RuntimeError("boom"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_invalid_url(hass: HomeAssistant) -> None:
    """An address without scheme is rejected before any request."""
    result = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_URL: "patchmon.example:3000"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_URL: "invalid_url"}


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The same server (in any spelling) cannot be added twice."""
    mock_config_entry.add_to_hass(hass)
    result = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert aioclient_mock.call_count == 0


async def test_reauth_flow(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Re-authentication asks only for key and secret and keeps the rest."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["url"] == URL

    aioclient_mock.get(f"{API}/hosts", status=401, json={"error": "Invalid API key"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN_KEY: "old", CONF_TOKEN_SECRET: "old"}
    )
    assert result["errors"] == {"base": "invalid_credentials"}

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API}/hosts", json=load_fixture("hosts.json"))
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN_KEY: "new-key", CONF_TOKEN_SECRET: "new-secret"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data == {
        **ENTRY_DATA,
        CONF_TOKEN_KEY: "new-key",
        CONF_TOKEN_SECRET: "new-secret",
    }


async def test_reconfigure_flow(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A new address updates unique ID and title; devices stay attached."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    aioclient_mock.get(
        "https://patchmon.lan/api/v1/api/hosts", json=load_fixture("hosts.json")
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_URL: "https://patchmon.lan/",
            CONF_TOKEN_KEY: "k2",
            CONF_TOKEN_SECRET: "s2",
            CONF_VERIFY_SSL: False,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.unique_id == "https://patchmon.lan"
    assert mock_config_entry.title == "PatchMon (patchmon.lan)"
    assert mock_config_entry.data == {
        CONF_URL: "https://patchmon.lan",
        CONF_TOKEN_KEY: "k2",
        CONF_TOKEN_SECRET: "s2",
        CONF_VERIFY_SSL: False,
    }


async def test_reconfigure_same_address(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Keeping the address and changing only the token works."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    aioclient_mock.get(f"{API}/hosts", json=load_fixture("hosts.json"))

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**ENTRY_DATA, CONF_TOKEN_SECRET: "rotated"}
    )

    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_TOKEN_SECRET] == "rotated"


async def test_reconfigure_keeps_secret_when_empty(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """An empty secret field keeps the stored secret."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    aioclient_mock.get(f"{API}/hosts", json=load_fixture("hosts.json"))

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**ENTRY_DATA, CONF_TOKEN_KEY: "new-key", CONF_TOKEN_SECRET: ""},
    )

    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_TOKEN_KEY] == "new-key"
    assert mock_config_entry.data[CONF_TOKEN_SECRET] == ENTRY_DATA[CONF_TOKEN_SECRET]
    # The stored secret was sent to PatchMon for the test request.
    _, _, _, headers = aioclient_mock.mock_calls[0]
    expected = base64.b64encode(f"new-key:{ENTRY_DATA[CONF_TOKEN_SECRET]}".encode())
    assert headers["Authorization"] == f"Basic {expected.decode()}"


async def test_reconfigure_errors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Invalid addresses and failing tests keep the form open."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**ENTRY_DATA, CONF_URL: "nope"}
    )
    assert result["errors"] == {CONF_URL: "invalid_url"}

    aioclient_mock.get(f"{API}/hosts", exc=TimeoutError())
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], ENTRY_DATA
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_to_other_configured_server(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Pointing an entry at a server another entry already uses is refused."""
    mock_config_entry.add_to_hass(hass)
    MockConfigEntry(
        domain=DOMAIN,
        unique_id="http://other.example:3000",
        data={**ENTRY_DATA, CONF_URL: "http://other.example:3000"},
    ).add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**ENTRY_DATA, CONF_URL: "http://OTHER.example:3000/"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


def _host_list_calls(mock: AiohttpClientMocker) -> list[yarl.URL]:
    """URLs of all GET /hosts requests (not the per-host details)."""
    return [url for _, url, _, _ in mock.mock_calls if url.path.endswith("/hosts")]


async def test_options_flow(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    area_registry: ar.AreaRegistry,
) -> None:
    """Groups come from PatchMon; saving stores the options and reloads."""
    area = area_registry.async_create("Server room")
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}
    selector = result["data_schema"].schema[CONF_HOST_GROUPS]
    assert [o["label"] for o in selector.config["options"]] == [
        "auto-updates",
        "security-only",
    ]

    lists_before = len(_host_list_calls(mock_hosts))
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCAN_INTERVAL: 10.0,
            CONF_HOST_GROUPS: ["00000000-0000-4000-8000-b00000000001"],
            CONF_AREA: area.id,
            CONF_OPTIONAL_ENTITIES: {"enable_running_kernel": True},
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_SCAN_INTERVAL: 10,
        CONF_HOST_GROUPS: ["00000000-0000-4000-8000-b00000000001"],
        CONF_AREA: area.id,
        **dict.fromkeys(ENABLE_OPTIONS, False),
        "enable_running_kernel": True,
    }
    # Reloaded with the new filter
    lists = _host_list_calls(mock_hosts)
    assert len(lists) == lists_before + 1
    assert lists[-1].query["hostgroup"] == "00000000-0000-4000-8000-b00000000001"


async def test_options_flow_server_unreachable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Without a connection the form still opens; stored groups are kept."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=URL,
        data=dict(ENTRY_DATA),
        options={CONF_SCAN_INTERVAL: 7, CONF_HOST_GROUPS: ["gone-group-id"]},
    )
    entry.add_to_hass(hass)
    aioclient_mock.get(f"{API}/hosts", exc=TimeoutError())

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    selector = result["data_schema"].schema[CONF_HOST_GROUPS]
    assert selector.config["options"] == [
        {"value": "gone-group-id", "label": "gone-group-id"}
    ]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 7, CONF_OPTIONAL_ENTITIES: {}}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_SCAN_INTERVAL: 7,
        CONF_HOST_GROUPS: ["gone-group-id"],
        **dict.fromkeys(ENABLE_OPTIONS, False),
    }


async def _save_options(
    hass: HomeAssistant, entry: MockConfigEntry, **switches: bool
) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCAN_INTERVAL: 5,
            # The frontend always sends every switch of the section.
            CONF_OPTIONAL_ENTITIES: {
                **dict.fromkeys(ENABLE_OPTIONS, False),
                **switches,
            },
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


def _disabled(registry: er.EntityRegistry, platform: str, key: str) -> list[bool]:
    """Disabled flag of the entity ``key`` of the four fixture hosts."""
    flags = []
    for number in range(1, 5):
        entity_id = registry.async_get_entity_id(
            platform, DOMAIN, f"{host_id(number)}_{key}"
        )
        assert entity_id is not None
        entry = registry.async_get(entity_id)
        assert entry is not None
        flags.append(entry.disabled_by is not None)
    return flags


async def test_options_switch_optional_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    entity_registry: er.EntityRegistry,
) -> None:
    """A switch enables or disables its entity on every host, only when switched."""
    await setup_entry(hass, mock_config_entry)
    assert _disabled(entity_registry, "update", "updates") == [True] * 4
    assert _disabled(entity_registry, "sensor", "running_kernel") == [True] * 4

    await _save_options(hass, mock_config_entry, enable_update_entity=True)

    assert _disabled(entity_registry, "update", "updates") == [False] * 4
    assert _disabled(entity_registry, "sensor", "running_kernel") == [True] * 4
    assert not _disabled(entity_registry, "sensor", "updates")[0]

    # A single entity switched by hand stays while other options are saved.
    kernel_1 = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{host_id(1)}_running_kernel"
    )
    assert kernel_1 is not None
    entity_registry.async_update_entity(kernel_1, disabled_by=None)
    await _save_options(hass, mock_config_entry, enable_update_entity=True)
    assert _disabled(entity_registry, "sensor", "running_kernel") == [
        False,
        True,
        True,
        True,
    ]

    await _save_options(hass, mock_config_entry)

    assert _disabled(entity_registry, "update", "updates") == [True] * 4
    disabler = entity_registry.async_get(kernel_1)
    assert disabler is not None
    assert disabler.disabled_by is None


async def test_new_hosts_follow_switch(
    hass: HomeAssistant,
    mock_hosts: AiohttpClientMocker,
    entity_registry: er.EntityRegistry,
) -> None:
    """Entities of new hosts are created enabled while the switch is on."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=URL,
        data=dict(ENTRY_DATA),
        options={"enable_installed_packages": True},
    )
    await setup_entry(hass, entry)

    assert _disabled(entity_registry, "sensor", "installed_packages") == [False] * 4
    assert _disabled(entity_registry, "sensor", "installed_kernel") == [True] * 4
