"""Tests for the PatchMon update entities."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import WebSocketGenerator
from syrupy.assertion import SnapshotAssertion

from custom_components.patchmon_hass.api import Package
from custom_components.patchmon_hass.update import _latest_version, _release_notes

from .conftest import API, host_id, load_fixture, platform_snapshot, setup_entry


async def test_disabled_by_default(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    entity_registry: er.EntityRegistry,
) -> None:
    """Update entities exist but are disabled until the user enables them."""
    await setup_entry(hass, mock_config_entry)

    entry = entity_registry.async_get("update.host_02_updates")
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


@pytest.mark.usefixtures("enable_all_entities")
async def test_update_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    snapshot: SnapshotAssertion,
) -> None:
    """Versions are labels: current against "N updates (M security)"."""
    await setup_entry(hass, mock_config_entry)

    assert platform_snapshot(hass, mock_config_entry, "update") == snapshot


@pytest.mark.usefixtures("enable_all_entities")
async def test_release_notes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
    hass_ws_client: WebSocketGenerator,
    snapshot: SnapshotAssertion,
) -> None:
    """The package list is read when the dialog opens."""
    await setup_entry(hass, mock_config_entry)
    mock_hosts.get(
        f"{API}/hosts/{host_id(2)}/packages",
        json=load_fixture("host_02_packages.json"),
    )
    client = await hass_ws_client(hass)

    await client.send_json(
        {"id": 1, "type": "update/release_notes", "entity_id": "update.host_02_updates"}
    )
    result = await client.receive_json()

    assert result["success"]
    assert result["result"] == snapshot
    _, url, _, _ = mock_hosts.mock_calls[-1]
    assert url.query["updates_only"] == "true"


@pytest.mark.usefixtures("enable_all_entities")
async def test_release_notes_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hosts: AiohttpClientMocker,
) -> None:
    """A failing package request is shown as an error."""
    await setup_entry(hass, mock_config_entry)
    mock_hosts.get(f"{API}/hosts/{host_id(2)}/packages", exc=TimeoutError())
    entity = hass.data["entity_components"]["update"].get_entity(
        "update.host_02_updates"
    )

    with pytest.raises(HomeAssistantError) as err:
        await entity.async_release_notes()
    assert err.value.translation_key == "packages_failed"


def test_latest_version_labels() -> None:
    """One update, several, with and without security updates, unknown."""
    assert _latest_version(None, None) is None
    assert _latest_version(0, 0) == "current"
    assert _latest_version(1, 0) == "1 update"
    assert _latest_version(16, 1) == "16 updates (1 security)"


def test_release_notes_limit() -> None:
    """At most 50 packages, security updates first, then by name."""
    packages = [
        Package.from_api({"name": f"pkg{i:02}", "needs_update": True})
        for i in range(60)
    ]
    packages.append(
        Package.from_api(
            {
                "name": "zz-sec",
                "current_version": "1",
                "available_version": "2",
                "is_security_update": True,
            }
        )
    )

    lines = _release_notes(packages).splitlines()

    assert lines[0] == "- **zz-sec** 1 → 2 (security)"
    assert lines[1] == "- **pkg00** ? → ?"
    assert len(lines) == 51
    assert lines[-1] == "- … 11 more"
