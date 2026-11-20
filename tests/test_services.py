"""Tests for the PatchMon actions."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from syrupy.assertion import SnapshotAssertion

from custom_components.patchmon_hass.const import DOMAIN

from .conftest import API, ENTRY_ID, host_id, load_fixture, mock_details, setup_entry


def _device_id(hass: HomeAssistant, ident: str) -> str:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, ident), ENTRY_ID
    )
    assert device is not None
    return device.id


async def _call(
    hass: HomeAssistant, service: str, data: dict[str, Any] | None = None
) -> Any:
    return await hass.services.async_call(
        DOMAIN, service, data or {}, blocking=True, return_response=True
    )


def _names(response: Any) -> list[str]:
    return [host["name"] for host in response["hosts"]]


def _detail_calls(aioclient_mock: AiohttpClientMocker) -> list[str]:
    return sorted(
        url.path.removeprefix("/api/v1/api/hosts/")
        for _, url, _, _ in aioclient_mock.mock_calls
        if not url.path.endswith("/hosts")
    )


async def test_get_hosts(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
) -> None:
    """All hosts of the last update, sorted by name, without asking PatchMon."""
    await setup_entry(hass, mock_config_entry)
    calls = mock_hosts.call_count

    response = await _call(hass, "get_hosts")

    assert mock_hosts.call_count == calls
    assert response["count"] == 4
    for host in response["hosts"]:
        host["device_id"] = bool(host["device_id"])
    assert response == snapshot


async def test_get_hosts_uses_device_name(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """A name given in Home Assistant wins; PatchMon's name is kept beside it."""
    await setup_entry(hass, mock_config_entry)
    dr.async_get(hass).async_update_device(
        _device_id(hass, host_id(3)), name_by_user="Aardvark"
    )

    response = await _call(hass, "get_hosts")

    assert _names(response) == ["Aardvark", "Host 01", "Host 02", "Host 04"]
    assert response["hosts"][0]["patchmon_name"] == "Host 03"


@pytest.mark.parametrize(
    ("data", "names"),
    [
        ({"update_status": ["security_required"]}, ["Host 02", "Host 04"]),
        ({"update_status": "up_to_date"}, ["Host 01"]),
        ({"restart_required": True}, ["Host 01", "Host 02"]),
        ({"restart_required": False}, ["Host 03", "Host 04"]),
        (
            {"update_status": ["security_required"], "restart_required": True},
            ["Host 02"],
        ),
        ({"reporting": False}, ["Host 03"]),
        ({"reporting": True}, ["Host 01", "Host 02"]),
    ],
)
async def test_get_hosts_filters(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    data: dict[str, Any],
    names: list[str],
) -> None:
    """Every filter given must match; unknown values match no filter."""
    hosts = load_fixture("hosts.json")
    hosts["hosts"][2]["reporting_state"] = "overdue"
    del hosts["hosts"][3]["reporting_state"]
    aioclient_mock.get(f"{API}/hosts", json=hosts)
    mock_details(aioclient_mock)
    await setup_entry(hass, mock_config_entry)

    assert _names(await _call(hass, "get_hosts", data)) == names


async def test_get_hosts_of_one_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """The entry ID limits the answer; unknown or unloaded entries are errors."""
    await setup_entry(hass, mock_config_entry)
    response = await _call(
        hass, "get_hosts", {"config_entry_id": mock_config_entry.entry_id}
    )
    assert response["count"] == 4

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "get_hosts", {"config_entry_id": "nope"})
    assert err.value.translation_key == "entry_not_found"

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "get_hosts", {"config_entry_id": mock_config_entry.entry_id})
    assert err.value.translation_key == "not_loaded"
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "get_hosts")
    assert err.value.translation_key == "not_loaded"


async def test_actions_without_entry(hass: HomeAssistant) -> None:
    """The actions exist without an entry and say so."""
    assert await async_setup_component(hass, DOMAIN, {})

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "get_hosts")
    assert err.value.translation_key == "not_loaded"


async def test_get_packages(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
) -> None:
    """Packages with updates, security first, read from PatchMon now."""
    await setup_entry(hass, mock_config_entry)
    mock_hosts.get(
        f"{API}/hosts/{host_id(2)}/packages",
        json=load_fixture("host_02_packages.json"),
    )
    device_id = _device_id(hass, host_id(2))

    response = await _call(hass, "get_packages", {"device_id": device_id, "limit": 3})

    assert mock_hosts.mock_calls[-1][1].query == {"updates_only": "true"}
    assert response["device_id"] == device_id
    response["device_id"] = None
    assert response == snapshot


async def test_get_packages_filters(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """All packages, security only, and descriptions on request."""
    await setup_entry(hass, mock_config_entry)
    packages = load_fixture("host_02_packages.json")
    packages["packages"][0]["needs_update"] = False
    mock_hosts.get(f"{API}/hosts/{host_id(2)}/packages", json=packages)
    device_id = _device_id(hass, host_id(2))

    everything = await _call(
        hass, "get_packages", {"device_id": device_id, "updates_only": False}
    )
    assert mock_hosts.mock_calls[-1][1].query == {}
    assert everything["total"] == 16
    assert not everything["truncated"]
    assert "description" not in everything["packages"][0]

    updates = await _call(hass, "get_packages", {"device_id": device_id})
    assert updates["total"] == 15

    security = await _call(
        hass,
        "get_packages",
        {
            "device_id": device_id,
            "updates_only": False,
            "security_only": True,
            "include_descriptions": True,
        },
    )
    assert mock_hosts.mock_calls[-1][1].query == {"updates_only": "true"}
    assert [p["name"] for p in security["packages"]] == ["sos"]
    assert security["packages"][0]["description"].startswith("Set of tools")


async def test_get_packages_device_errors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """The server device, foreign devices and unknown IDs are rejected."""
    await setup_entry(hass, mock_config_entry)
    other = MockConfigEntry(domain="other")
    other.add_to_hass(hass)
    foreign = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("other", "x")}
    )

    for device_id, key in (
        (_device_id(hass, mock_config_entry.entry_id), "not_a_host"),
        (foreign.id, "device_not_found"),
        ("nope", "device_not_found"),
    ):
        with pytest.raises(ServiceValidationError) as err:
            await _call(hass, "get_packages", {"device_id": device_id})
        assert err.value.translation_key == key

    host_device = _device_id(hass, host_id(2))
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "get_packages", {"device_id": host_device})
    assert err.value.translation_key == "not_loaded"


@pytest.mark.parametrize(
    ("kwargs", "key"),
    [
        ({"status": 404, "json": load_fixture("error_404.json")}, "host_not_found"),
        ({"status": 503, "text": ""}, "cannot_connect"),
        ({"status": 200, "text": "<html></html>"}, "unsupported"),
        ({"status": 401, "json": load_fixture("error_401.json")}, "auth_failed"),
    ],
)
async def test_get_packages_request_errors(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    kwargs: dict[str, Any],
    key: str,
) -> None:
    """Failed requests give translated errors; a rejected token starts reauth."""
    await setup_entry(hass, mock_config_entry)
    mock_hosts.get(f"{API}/hosts/{host_id(2)}/packages", **kwargs)

    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, "get_packages", {"device_id": _device_id(hass, host_id(2))})
    assert err.value.translation_key == key

    flows = hass.config_entries.flow.async_progress()
    assert bool(flows) is (key == "auth_failed")
    if flows:
        assert flows[0]["context"]["source"] == SOURCE_REAUTH


async def test_refresh_all(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """Without devices, the host list and every host's details are read."""
    await setup_entry(hass, mock_config_entry)
    mock_hosts.mock_calls.clear()

    await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)

    assert len(_detail_calls(mock_hosts)) == 8

    # The next regular update reads no details again.
    mock_hosts.mock_calls.clear()
    await mock_config_entry.runtime_data.coordinator.async_refresh()
    assert _detail_calls(mock_hosts) == []


async def test_refresh_devices(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """Host devices re-read their details; the server device stands for all."""
    await setup_entry(hass, mock_config_entry)
    mock_hosts.mock_calls.clear()

    await hass.services.async_call(
        DOMAIN,
        "refresh",
        {"device_id": [_device_id(hass, host_id(1)), _device_id(hass, host_id(3))]},
        blocking=True,
    )
    assert _detail_calls(mock_hosts) == [
        f"{host_id(1)}/info",
        f"{host_id(1)}/system",
        f"{host_id(3)}/info",
        f"{host_id(3)}/system",
    ]

    mock_hosts.mock_calls.clear()
    await hass.services.async_call(
        DOMAIN,
        "refresh",
        {
            "device_id": [
                _device_id(hass, host_id(1)),
                _device_id(hass, mock_config_entry.entry_id),
                _device_id(hass, host_id(2)),
            ]
        },
        blocking=True,
    )
    assert len(_detail_calls(mock_hosts)) == 8


async def test_refresh_failure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """A failed refresh is reported with the reason of the update."""
    await setup_entry(hass, mock_config_entry)
    mock_hosts.clear_requests()
    mock_hosts.get(f"{API}/hosts", status=503)

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    assert err.value.translation_key == "cannot_connect"
    assert err.value.translation_placeholders == {"error": "HTTP 503"}


async def test_refresh_unexpected_failure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """Errors without a translation are wrapped in a generic one."""
    await setup_entry(hass, mock_config_entry)
    mock_hosts.clear_requests()
    mock_hosts.get(f"{API}/hosts", exc=RuntimeError("boom"))

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    assert err.value.translation_key == "refresh_failed"
    assert err.value.translation_placeholders == {"error": "boom"}
