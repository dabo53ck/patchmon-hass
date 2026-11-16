"""Tests for the read-only PatchMon API client."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.patchmon_hass.api import (
    AuthFailure,
    PatchMonAuthError,
    PatchMonClient,
    PatchMonConnectionError,
    PatchMonNotFoundError,
    PatchMonSSLError,
    PatchMonUnsupportedError,
    normalize_url,
)

from .conftest import API, HOST_01, URL, load_fixture


@pytest.fixture
async def client(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> PatchMonClient:
    """A client on Home Assistant's (mocked) session."""
    return PatchMonClient(async_get_clientsession(hass), URL, "key", "secret")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://patchmon.example:3000", "http://patchmon.example:3000"),
        ("  HTTP://PatchMon.Example:3000/  ", "http://patchmon.example:3000"),
        ("http://patchmon.example:3000/api/v1/api/", "http://patchmon.example:3000"),
        ("https://patchmon.example/api/v1", "https://patchmon.example"),
        ("https://proxy.example/patchmon/", "https://proxy.example/patchmon"),
        ("http://[fd00::1]:3000", "http://[fd00::1]:3000"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    """Pasted addresses are reduced to one canonical form."""
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "patchmon.example:3000", "ftp://x", "http://"])
def test_normalize_url_rejects(raw: str) -> None:
    """Anything that is not an http(s) URL is rejected."""
    with pytest.raises(ValueError):
        normalize_url(raw)


async def test_get_hosts(
    client: PatchMonClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """The host list is parsed into typed hosts, with stats requested."""
    aioclient_mock.get(f"{API}/hosts", json=load_fixture("hosts.json"))

    hosts = await client.get_hosts()

    assert len(hosts) == 4
    first = hosts[0]
    assert first.id == HOST_01
    assert first.friendly_name == "Host 01"
    assert first.hostname == "host-01"
    assert first.update_state == "up_to_date"
    assert first.reporting_state == "reporting"
    assert first.needs_reboot is True
    assert first.updates_count == 0
    assert first.total_packages == 429
    assert first.last_update == datetime(2026, 11, 16, 18, 45, 22, tzinfo=UTC)
    assert first.host_groups[0].name == "auto-updates"
    assert [h.update_state for h in hosts] == [
        "up_to_date",
        "security_required",
        "updates_pending",
        "security_required",
    ]
    assert hosts[1].security_updates_count == 1
    _, url, _, headers = aioclient_mock.mock_calls[0]
    assert url.query["include"] == "stats"
    assert "hostgroup" not in url.query
    # HTTP Basic auth with "key:secret"
    assert headers == {"Authorization": "Basic a2V5OnNlY3JldA=="}


async def test_get_hosts_group_filter(
    client: PatchMonClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Host groups are sent comma separated; unknown groups give no hosts."""
    aioclient_mock.get(f"{API}/hosts", json=load_fixture("hosts_unknown_group.json"))

    assert await client.get_hosts(["a", "b"]) == []
    _, url, _, _ = aioclient_mock.mock_calls[0]
    assert url.query["hostgroup"] == "a,b"


async def test_get_hosts_old_server_fields_missing(
    client: PatchMonClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Hosts from servers without the newer fields still load."""
    aioclient_mock.get(
        f"{API}/hosts",
        json={
            "hosts": [
                {"id": "x", "hostname": "only-hostname", "updates_count": True},
                {"id": "y", "last_update": "not a date", "host_groups": ["bad"]},
            ]
        },
    )

    first, second = await client.get_hosts()

    assert first.friendly_name == "only-hostname"
    assert first.update_state is None
    assert first.reporting_state is None
    assert first.needs_reboot is None
    assert first.updates_count is None  # a bool is not a count
    assert second.friendly_name == "y"
    assert second.last_update is None
    assert second.host_groups == ()


async def test_get_host_details(
    client: PatchMonClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """System, info and package answers are parsed."""
    aioclient_mock.get(
        f"{API}/hosts/{HOST_01}/system", json=load_fixture("host_01_system.json")
    )
    aioclient_mock.get(
        f"{API}/hosts/{HOST_01}/info", json=load_fixture("host_01_info.json")
    )
    aioclient_mock.get(
        f"{API}/hosts/{HOST_01}/packages", json=load_fixture("host_02_packages.json")
    )

    system = await client.get_host_system(HOST_01)
    assert system.needs_reboot is True
    assert system.kernel_version != system.installed_kernel_version
    assert system.reboot_reason is not None
    assert system.reboot_reason.startswith("Kernel version mismatch")
    assert system.boot_time is not None

    info = await client.get_host_info(HOST_01)
    assert info.agent_version == "2.1.8"
    assert info.machine_id is not None

    packages = await client.get_host_packages(HOST_01)
    assert len(packages) == 16
    assert any(p.is_security_update for p in packages)
    assert all(p.needs_update for p in packages)
    _, url, _, _ = aioclient_mock.mock_calls[-1]
    assert url.query["updates_only"] == "true"


async def test_get_all_packages(
    client: PatchMonClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """updates_only=False asks for every package."""
    aioclient_mock.get(
        f"{API}/hosts/{HOST_01}/packages", json=load_fixture("host_01_packages.json")
    )

    assert await client.get_host_packages(HOST_01, updates_only=False) == []
    _, url, _, _ = aioclient_mock.mock_calls[0]
    assert "updates_only" not in url.query


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (401, load_fixture("error_401.json"), AuthFailure.INVALID_CREDENTIALS),
        (401, {"error": "API key is disabled"}, AuthFailure.TOKEN_DISABLED),
        (401, {"error": "API key has expired"}, AuthFailure.TOKEN_EXPIRED),
        (401, None, AuthFailure.INVALID_CREDENTIALS),
        (403, {"error": "IP address not allowed"}, AuthFailure.IP_NOT_ALLOWED),
        (
            403,
            {
                "error": "Access denied",
                "message": "This API key does not have permission to get host",
            },
            AuthFailure.MISSING_PERMISSION,
        ),
        (403, None, AuthFailure.MISSING_PERMISSION),
    ],
)
async def test_auth_errors(
    client: PatchMonClient,
    aioclient_mock: AiohttpClientMocker,
    status: int,
    body: dict[str, str] | None,
    reason: AuthFailure,
) -> None:
    """401 and 403 are classified by PatchMon's error text."""
    aioclient_mock.get(f"{API}/hosts", status=status, json=body)

    with pytest.raises(PatchMonAuthError) as err:
        await client.get_hosts()
    assert err.value.reason is reason
    assert err.value.message


async def test_not_found(
    client: PatchMonClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A deleted host answers 404."""
    aioclient_mock.get(
        f"{API}/hosts/{HOST_01}/info", status=404, json=load_fixture("error_404.json")
    )

    with pytest.raises(PatchMonNotFoundError):
        await client.get_host_info(HOST_01)


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError(),
        aiohttp.ClientConnectionError(),
        aiohttp.ClientError("boom"),
    ],
)
async def test_connection_errors(
    client: PatchMonClient, aioclient_mock: AiohttpClientMocker, exc: Exception
) -> None:
    """Network problems become PatchMonConnectionError."""
    aioclient_mock.get(f"{API}/hosts", exc=exc)

    with pytest.raises(PatchMonConnectionError) as err:
        await client.get_hosts()
    assert not isinstance(err.value, PatchMonSSLError)
    assert str(err.value)


async def test_ssl_error(
    client: PatchMonClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Certificate problems are reported separately."""
    aioclient_mock.get(
        f"{API}/hosts", exc=aiohttp.ClientSSLError(MagicMock(), OSError("bad cert"))
    )

    with pytest.raises(PatchMonSSLError):
        await client.get_hosts()


async def test_server_error(
    client: PatchMonClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 5xx answer counts as a (temporary) connection problem."""
    aioclient_mock.get(f"{API}/hosts", status=500, json={"error": "Failed"})

    with pytest.raises(PatchMonConnectionError, match="HTTP 500"):
        await client.get_hosts()


@pytest.mark.parametrize(
    ("status", "text"),
    [
        (200, "<!doctype html><title>PatchMon</title>"),
        (200, ""),
        (302, ""),
        (400, '{"error": "Invalid host ID format"}'),
    ],
)
async def test_unexpected_answers(
    client: PatchMonClient,
    aioclient_mock: AiohttpClientMocker,
    status: int,
    text: str,
) -> None:
    """HTML, empty bodies, redirects and other codes are not supported."""
    aioclient_mock.get(f"{API}/hosts", status=status, text=text)

    with pytest.raises(PatchMonUnsupportedError):
        await client.get_hosts()


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"total": 0},
        {"hosts": "nope"},
        {"hosts": [{"hostname": "no id"}]},
        {"hosts": ["not an object"]},
    ],
)
async def test_malformed_host_list(
    client: PatchMonClient, aioclient_mock: AiohttpClientMocker, body: object
) -> None:
    """A host list in an unknown shape is reported as unsupported."""
    aioclient_mock.get(f"{API}/hosts", json=body)

    with pytest.raises(PatchMonUnsupportedError):
        await client.get_hosts()


@pytest.mark.parametrize(
    ("endpoint", "method", "body"),
    [
        ("system", "get_host_system", []),
        ("info", "get_host_info", "text"),
        ("packages", "get_host_packages", {"total": 0}),
        ("packages", "get_host_packages", {"packages": [{"current_version": "1"}]}),
    ],
)
async def test_malformed_host_details(
    client: PatchMonClient,
    aioclient_mock: AiohttpClientMocker,
    endpoint: str,
    method: str,
    body: object,
) -> None:
    """Detail answers in an unknown shape are reported as unsupported."""
    aioclient_mock.get(f"{API}/hosts/{HOST_01}/{endpoint}", json=body)

    with pytest.raises(PatchMonUnsupportedError):
        await getattr(client, method)(HOST_01)
