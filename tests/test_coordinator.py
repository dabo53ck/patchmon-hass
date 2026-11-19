"""Tests for the PatchMon data update coordinator."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.patchmon_hass.api import Host
from custom_components.patchmon_hass.const import CONF_HOST_GROUPS, DOMAIN
from custom_components.patchmon_hass.coordinator import (
    ISSUE_GROUPS_WITHOUT_HOSTS,
    ISSUE_UNSUPPORTED,
    PatchMonCoordinator,
    _update_state,
)

from .conftest import API, ENTRY_DATA, URL, host_id, load_fixture, mock_details

GROUP_AUTO = "00000000-0000-4000-8000-b00000000001"
GROUP_GONE = "00000000-0000-4000-8000-b0000000dead"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> PatchMonCoordinator:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data.coordinator


def _remock(aioclient_mock: AiohttpClientMocker, hosts: dict[str, Any]) -> None:
    """Replace all answers: the given host list plus the fixture details."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API}/hosts", json=hosts)
    mock_details(aioclient_mock)


def _detail_calls(aioclient_mock: AiohttpClientMocker) -> list[str]:
    return [
        url.path.removeprefix("/api/v1/api/hosts/")
        for _, url, _, _ in aioclient_mock.mock_calls
        if not url.path.endswith("/hosts")
    ]


@pytest.mark.parametrize(
    ("updates", "security", "state"),
    [(5, 2, "security_required"), (5, 0, "updates_pending"), (0, 0, "up_to_date")],
)
def test_update_state_from_counters(updates: int, security: int, state: str) -> None:
    """Servers without ``update_state`` get it derived like PatchMon does."""
    host = Host.from_api(
        {"id": "x", "updates_count": updates, "security_updates_count": security}
    )
    assert _update_state(host).update_state == state


def test_update_state_kept_or_unknown() -> None:
    """A server value wins; without counters the state stays unknown."""
    given = Host.from_api({"id": "x", "update_state": "up_to_date", "updates_count": 3})
    assert _update_state(given) is given
    assert _update_state(Host.from_api({"id": "y"})).update_state is None


async def test_details_only_after_new_report(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Details are re-read only for hosts whose agent reported again."""
    caplog.set_level(logging.DEBUG, logger="custom_components.patchmon_hass")
    coordinator = await _setup(hass, mock_config_entry)
    hosts = load_fixture("hosts.json")

    _remock(mock_hosts, hosts)
    await coordinator.async_refresh()
    assert mock_hosts.call_count == 1
    assert len(coordinator.data.details) == 4

    hosts["hosts"][0]["last_update"] = "2026-11-16T19:45:22Z"
    _remock(mock_hosts, hosts)
    await coordinator.async_refresh()
    assert sorted(_detail_calls(mock_hosts)) == [
        f"{host_id(1)}/info",
        f"{host_id(1)}/system",
    ]
    assert "Reading details of 1 hosts" in caplog.text
    assert "4 hosts listed, details available for 4" in caplog.text
    assert "(refresh action)" not in caplog.text

    _remock(mock_hosts, hosts)
    await coordinator.async_refresh_now()
    assert len(_detail_calls(mock_hosts)) == 8
    assert "details available for 4 (refresh action)" in caplog.text


async def test_details_reread_after_max_age(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Details older than six hours are read again even without a report."""
    coordinator = await _setup(hass, mock_config_entry)

    freezer.tick(timedelta(hours=6))
    _remock(mock_hosts, load_fixture("hosts.json"))
    await coordinator.async_refresh()

    assert len(_detail_calls(mock_hosts)) == 8


async def test_details_failure_only_affects_that_host(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A host whose details fail keeps its host data; the others are complete."""
    aioclient_mock.get(f"{API}/hosts", json=load_fixture("hosts.json"))
    aioclient_mock.get(f"{API}/hosts/{host_id(2)}/system", status=500)
    mock_details(aioclient_mock)

    coordinator = await _setup(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert len(coordinator.data.hosts) == 4
    assert set(coordinator.data.details) == {host_id(1), host_id(3), host_id(4)}
    details = coordinator.data.details[host_id(1)]
    assert details.system.needs_reboot is True
    assert details.info.agent_version is not None


async def test_details_404_keeps_host(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A 404 on the details only drops the details; the host list decides.

    A proxy or another server version can answer every detail path with 404
    while the host list is fine: that must not remove any host.
    """
    aioclient_mock.get(f"{API}/hosts", json=load_fixture("hosts.json"))
    for n in range(1, 5):
        aioclient_mock.get(f"{API}/hosts/{host_id(n)}/system", status=404, text="")

    coordinator = await _setup(hass, mock_config_entry)

    assert coordinator.last_update_success
    assert len(coordinator.data.hosts) == 4
    assert coordinator.data.details == {}
    assert coordinator.data.complete


async def test_parallel_refresh_keeps_each_request(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """Two refresh actions at once both get the details they asked for."""
    coordinator = await _setup(hass, mock_config_entry)
    _remock(mock_hosts, load_fixture("hosts.json"))

    await asyncio.gather(
        coordinator.async_refresh_now([host_id(1)]),
        coordinator.async_refresh_now([host_id(2)]),
    )

    assert {call.split("/")[0] for call in _detail_calls(mock_hosts)} == {
        host_id(1),
        host_id(2),
    }


async def test_details_auth_error_starts_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A rejected token while reading details starts re-authentication."""
    aioclient_mock.get(f"{API}/hosts", json=load_fixture("hosts.json"))
    aioclient_mock.get(
        f"{API}/hosts/{host_id(1)}/info",
        status=401,
        json=load_fixture("error_401.json"),
    )
    mock_details(aioclient_mock)
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_unexpected_error_is_not_swallowed(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """Bugs in reading details surface instead of being logged away."""
    with patch(
        "custom_components.patchmon_hass.api.PatchMonClient.get_host_info",
        side_effect=RuntimeError("boom"),
    ):
        mock_config_entry.add_to_hass(hass)
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_poll_failure_keeps_data(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """An unreachable server marks the update failed and keeps the old data."""
    coordinator = await _setup(hass, mock_config_entry)
    mock_hosts.clear_requests()
    mock_hosts.get(f"{API}/hosts", exc=TimeoutError())

    await coordinator.async_refresh()

    assert not coordinator.last_update_success
    assert len(coordinator.data.hosts) == 4


async def test_filter_group_without_hosts(
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A deleted or empty filter group raises a repair and blocks removals."""
    caplog.set_level(logging.DEBUG, logger="custom_components.patchmon_hass")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="PatchMon (patchmon.example)",
        unique_id=URL,
        data=dict(ENTRY_DATA),
        options={CONF_HOST_GROUPS: [GROUP_AUTO, GROUP_GONE]},
    )
    hosts = load_fixture("hosts.json")
    auto_only = {
        "hosts": [h for h in hosts["hosts"] if h["host_groups"][0]["id"] == GROUP_AUTO]
    }
    _remock(aioclient_mock, auto_only)

    coordinator = await _setup(hass, entry)

    assert coordinator.data.groups_without_hosts == (GROUP_GONE,)
    assert not coordinator.data.complete
    assert f"filter groups without hosts: {GROUP_GONE}" in caplog.text
    assert "no device is removed" in caplog.text
    assert len(coordinator.data.hosts) == 2
    issue = issue_registry.async_get_issue(
        DOMAIN, f"{ISSUE_GROUPS_WITHOUT_HOSTS}_{entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_placeholders == {
        "title": "PatchMon (patchmon.example)",
        "groups": GROUP_GONE,
    }

    # The group gets hosts again (or the filter is fixed): the repair goes away.
    gone = dict(hosts["hosts"][1])
    gone["host_groups"] = [{"id": GROUP_GONE, "name": "gone"}]
    _remock(aioclient_mock, {"hosts": [*auto_only["hosts"], gone]})
    await coordinator.async_refresh()

    assert coordinator.data.complete
    assert not issue_registry.async_get_issue(
        DOMAIN, f"{ISSUE_GROUPS_WITHOUT_HOSTS}_{entry.entry_id}"
    )

    # Removing the entry also removes a pending repair.
    _remock(aioclient_mock, auto_only)
    await coordinator.async_refresh()
    await hass.config_entries.async_remove(entry.entry_id)
    assert not issue_registry.async_get_issue(
        DOMAIN, f"{ISSUE_GROUPS_WITHOUT_HOSTS}_{entry.entry_id}"
    )


async def test_suddenly_empty_list_is_incomplete(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """An empty list after known hosts must not count as "all deleted"."""
    coordinator = await _setup(hass, mock_config_entry)
    _remock(mock_hosts, {"hosts": [], "total": 0})

    await coordinator.async_refresh()

    assert coordinator.data.hosts == {}
    assert not coordinator.data.complete


async def test_unsupported_answer_raises_repair(
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """An answer we do not understand raises a repair at once; it goes away."""
    issue_id = f"{ISSUE_UNSUPPORTED}_{mock_config_entry.entry_id}"
    aioclient_mock.get(f"{API}/hosts", status=200, text="<html></html>")
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)

    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.translation_placeholders == {
        "title": "PatchMon (patchmon.example)",
        "error": "Unexpected answer (HTTP 200)",
    }

    _remock(aioclient_mock, load_fixture("hosts.json"))
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


async def test_unsupported_details_raise_repair(
    hass: HomeAssistant,
    issue_registry: ir.IssueRegistry,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Details we do not understand raise it too; removing the entry drops it."""
    issue_id = f"{ISSUE_UNSUPPORTED}_{mock_config_entry.entry_id}"
    aioclient_mock.get(f"{API}/hosts", json=load_fixture("hosts.json"))
    aioclient_mock.get(f"{API}/hosts/{host_id(2)}/system", json=[])
    mock_details(aioclient_mock)

    coordinator = await _setup(hass, mock_config_entry)

    assert host_id(2) not in coordinator.data.details
    issue = issue_registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders is not None
    assert issue.translation_placeholders["error"] == "System details are not an object"

    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None
