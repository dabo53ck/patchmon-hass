"""Read-only client for the PatchMon Integration API.

Kept free of Home Assistant imports so it can be split into its own package
later. Only GET requests exist here: the integration never changes anything
in PatchMon, and the one write endpoint of the Integration API
(``DELETE /hosts/{id}``) is deliberately not implemented.

API reference: ``<server>/api/v1/docs`` on any PatchMon 2.x server. All
endpoints live under ``/api/v1/api`` and use HTTP Basic auth with an API
token (key and secret) that has the ``host:get`` scope.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import socket
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import aiohttp

_LOGGER = logging.getLogger(__name__)

API_PATH = "/api/v1/api"
DEFAULT_TIMEOUT = 15
MAX_PARALLEL_REQUESTS = 4


class PatchMonError(Exception):
    """Base class for all PatchMon client errors."""


class PatchMonConnectionError(PatchMonError):
    """Server unreachable, timed out or answered with a server error (5xx)."""


class PatchMonSSLError(PatchMonConnectionError):
    """TLS handshake or certificate verification failed."""


class AuthFailure(StrEnum):
    """Why PatchMon rejected the API token (401 or 403)."""

    INVALID_CREDENTIALS = "invalid_credentials"
    TOKEN_DISABLED = "token_disabled"
    TOKEN_EXPIRED = "token_expired"
    IP_NOT_ALLOWED = "ip_not_allowed"
    MISSING_PERMISSION = "missing_permission"


class PatchMonAuthError(PatchMonError):
    """The API token was rejected; ``reason`` says why."""

    def __init__(self, reason: AuthFailure, message: str) -> None:
        """Store the classified reason and PatchMon's own message."""
        super().__init__(message)
        self.reason = reason
        self.message = message


class PatchMonNotFoundError(PatchMonError):
    """The requested host does not exist (any more)."""


class PatchMonUnsupportedError(PatchMonError):
    """The answer does not look like a supported PatchMon server."""


class PatchMonRedirectError(PatchMonUnsupportedError):
    """The address redirects (http to https, a proxy login page, ...)."""


# Exact error texts of PatchMon 2.x (internal/middleware/api_auth.go and
# api_scope.go). Anything else on a 401 counts as invalid credentials.
_AUTH_MESSAGES: dict[str, AuthFailure] = {
    "API key is disabled": AuthFailure.TOKEN_DISABLED,
    "API key has expired": AuthFailure.TOKEN_EXPIRED,
    "IP address not allowed": AuthFailure.IP_NOT_ALLOWED,
}


def normalize_url(url: str) -> str:
    """Return the server address in a canonical form.

    Accepts what users typically paste (trailing slash, upper case host,
    the full ``/api/v1/api`` path) and returns ``scheme://host[:port][/path]``.
    Raises ``ValueError`` when the address is not an http(s) URL.
    """
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError(f"Not an http(s) URL: {url!r}")
    path = parts.path.rstrip("/")
    for suffix in (API_PATH, "/api/v1"):
        if path.endswith(suffix):
            path = path.removesuffix(suffix)
            break
    netloc = parts.hostname.lower()
    if ":" in netloc:  # IPv6 literal
        netloc = f"[{netloc}]"
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme.lower(), netloc, path, "", ""))


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # Timestamp sensors need an aware datetime; PatchMon sends UTC.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _opt_str(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) and value else None


def _opt_int(data: Mapping[str, Any], key: str) -> int | None:
    value = data.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _opt_bool(data: Mapping[str, Any], key: str) -> bool | None:
    value = data.get(key)
    return value if isinstance(value, bool) else None


def _require_id(data: Any) -> str:
    if not isinstance(data, Mapping) or not isinstance(data.get("id"), str):
        raise PatchMonUnsupportedError("Host entry without an id")
    return str(data["id"])


@dataclass(frozen=True, slots=True)
class HostGroup:
    """A PatchMon host group."""

    id: str
    name: str

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> HostGroup:
        """Build from an API object."""
        return cls(id=str(data.get("id", "")), name=str(data.get("name", "")))


@dataclass(frozen=True, slots=True)
class Host:
    """One host from ``GET /hosts?include=stats``.

    Fields newer PatchMon versions added (``reporting_state``,
    ``update_state``) are optional so older servers still load.
    """

    id: str
    friendly_name: str
    hostname: str | None
    ip: str | None
    host_groups: tuple[HostGroup, ...]
    os_type: str | None
    os_version: str | None
    status: str | None
    effective_status: str | None
    reporting_state: str | None
    update_state: str | None
    last_update: datetime | None
    needs_reboot: bool | None
    updates_count: int | None
    security_updates_count: int | None
    total_packages: int | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Host:
        """Build from an API object."""
        host_id = _require_id(data)
        groups = data.get("host_groups") or []
        return cls(
            id=host_id,
            friendly_name=_opt_str(data, "friendly_name")
            or _opt_str(data, "hostname")
            or host_id,
            hostname=_opt_str(data, "hostname"),
            ip=_opt_str(data, "ip"),
            host_groups=tuple(
                HostGroup.from_api(g) for g in groups if isinstance(g, Mapping)
            ),
            os_type=_opt_str(data, "os_type"),
            os_version=_opt_str(data, "os_version"),
            status=_opt_str(data, "status"),
            effective_status=_opt_str(data, "effective_status"),
            reporting_state=_opt_str(data, "reporting_state"),
            update_state=_opt_str(data, "update_state"),
            last_update=_parse_datetime(data.get("last_update")),
            needs_reboot=_opt_bool(data, "needs_reboot"),
            updates_count=_opt_int(data, "updates_count"),
            security_updates_count=_opt_int(data, "security_updates_count"),
            total_packages=_opt_int(data, "total_packages"),
        )


@dataclass(frozen=True, slots=True)
class HostSystem:
    """System details from ``GET /hosts/{id}/system`` (the parts we use)."""

    architecture: str | None
    kernel_version: str | None
    installed_kernel_version: str | None
    needs_reboot: bool | None
    reboot_reason: str | None
    boot_time: datetime | None
    system_uptime: str | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> HostSystem:
        """Build from an API object."""
        return cls(
            architecture=_opt_str(data, "architecture"),
            kernel_version=_opt_str(data, "kernel_version"),
            installed_kernel_version=_opt_str(data, "installed_kernel_version"),
            needs_reboot=_opt_bool(data, "needs_reboot"),
            reboot_reason=_opt_str(data, "reboot_reason"),
            boot_time=_parse_datetime(data.get("boot_time")),
            system_uptime=_opt_str(data, "system_uptime"),
        )


@dataclass(frozen=True, slots=True)
class HostInfo:
    """Agent details from ``GET /hosts/{id}/info`` (the parts we use)."""

    agent_version: str | None
    config_version: str | None
    machine_id: str | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> HostInfo:
        """Build from an API object."""
        return cls(
            agent_version=_opt_str(data, "agent_version"),
            config_version=_opt_str(data, "config_version"),
            machine_id=_opt_str(data, "machine_id"),
        )


@dataclass(frozen=True, slots=True)
class Package:
    """One package from ``GET /hosts/{id}/packages``."""

    name: str
    current_version: str | None
    available_version: str | None
    needs_update: bool
    is_security_update: bool
    description: str | None
    category: str | None
    last_checked: datetime | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Package:
        """Build from an API object."""
        if not isinstance(data.get("name"), str):
            raise PatchMonUnsupportedError("Package entry without a name")
        return cls(
            name=str(data["name"]),
            current_version=_opt_str(data, "current_version"),
            available_version=_opt_str(data, "available_version"),
            needs_update=bool(data.get("needs_update")),
            is_security_update=bool(data.get("is_security_update")),
            description=_opt_str(data, "description"),
            category=_opt_str(data, "category"),
            last_checked=_parse_datetime(data.get("last_checked")),
        )


def _describe(err: BaseException) -> str:
    """Error type plus reason, without the server address.

    aiohttp puts host and port (or the URL) into its messages, and these
    texts end up in logs and in the Home Assistant interface.
    """
    name = type(err).__name__
    reason: object = None
    if isinstance(err, aiohttp.ClientConnectorCertificateError):
        reason = getattr(err.certificate_error, "reason", None)
    elif isinstance(err, aiohttp.ClientConnectorError):
        reason = getattr(err.os_error, "reason", None) or _os_reason(err.os_error)
    elif isinstance(err, OSError):
        reason = _os_reason(err)
    return f"{name} ({reason})" if reason else name


def _os_reason(err: OSError) -> str | None:
    """The standard text for the error number; asyncio adds the address."""
    if isinstance(err, socket.gaierror):
        return err.strerror  # "Name or service not known", without the name
    return os.strerror(err.errno) if err.errno else None


class HostList(list[Host]):
    """The host list, plus the number of hosts PatchMon says it has.

    ``total`` is None when the answer has no count. A ``total`` above the
    length means the list is cut off (PatchMon 2.x does not page it, but
    a later version might).
    """

    __slots__ = ("total",)

    def __init__(self, hosts: Iterable[Host] = (), total: int | None = None) -> None:
        """Store the hosts and the reported count."""
        super().__init__(hosts)
        self.total = total

    @property
    def truncated(self) -> bool:
        """Whether PatchMon reported more hosts than the list holds."""
        return self.total is not None and self.total > len(self)


def _host_path(host_id: str, part: str) -> str:
    """Path below one host; the ID is encoded so it stays one path segment."""
    return f"/hosts/{quote(host_id, safe='')}/{part}"


class PatchMonClient:
    """Async, read-only client for one PatchMon server."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        token_key: str,
        token_secret: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Set up the client; ``session`` is owned by the caller."""
        self._session = session
        self._base = normalize_url(url) + API_PATH
        # HTTP Basic auth built by hand: aiohttp deprecates BasicAuth and
        # ``auth=`` while its replacement is missing from older releases.
        credentials = base64.b64encode(f"{token_key}:{token_secret}".encode())
        self._headers = {"Authorization": f"Basic {credentials.decode('ascii')}"}
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._semaphore = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)

    async def _get(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        """GET ``path`` and return the decoded JSON body.

        Logs path, status and duration at debug level; never the server
        address or the token.
        """
        start = time.monotonic()
        try:
            async with (
                self._semaphore,
                self._session.get(
                    self._base + path,
                    params=params,
                    headers=self._headers,
                    timeout=self._timeout,
                    allow_redirects=False,
                ) as resp,
            ):
                text = await resp.text()
                status = resp.status
        except UnicodeDecodeError as err:
            # Binary or wrongly encoded body, e.g. from a proxy.
            raise PatchMonUnsupportedError("Answer is not valid text") from err
        except aiohttp.ClientSSLError as err:
            raise PatchMonSSLError(_describe(err)) from err
        except (TimeoutError, aiohttp.ClientError) as err:
            _LOGGER.debug(
                "GET %s failed after %.2f s: %s",
                path,
                time.monotonic() - start,
                type(err).__name__,
            )
            raise PatchMonConnectionError(_describe(err)) from err
        _LOGGER.debug(
            "GET %s: HTTP %s in %.2f s", path, status, time.monotonic() - start
        )

        body: Any
        try:
            body = json.loads(text) if text else None
        except ValueError:
            body = None

        if status in (401, 403):
            raise self._auth_error(status, body)
        if status == 404:
            raise PatchMonNotFoundError(path)
        if status >= 500:
            raise PatchMonConnectionError(f"HTTP {status}")
        if 300 <= status < 400:
            # Redirects are not followed: the token would go to the new
            # address. The target is left out, it holds an address too.
            raise PatchMonRedirectError(f"Redirect (HTTP {status})")
        if status != 200 or body is None:
            # Typical when the address points at the web interface or a
            # proxy: HTML instead of JSON.
            raise PatchMonUnsupportedError(f"Unexpected answer (HTTP {status})")
        return body

    @staticmethod
    def _auth_error(status: int, body: Any) -> PatchMonAuthError:
        error = message = ""
        if isinstance(body, Mapping):
            error = str(body.get("error", ""))
            message = str(body.get("message", ""))
        if error in _AUTH_MESSAGES:
            return PatchMonAuthError(_AUTH_MESSAGES[error], error)
        if status == 403:
            # "Access denied" + "This API key does not have permission to ..."
            return PatchMonAuthError(
                AuthFailure.MISSING_PERMISSION, message or error or "HTTP 403"
            )
        return PatchMonAuthError(AuthFailure.INVALID_CREDENTIALS, error or "HTTP 401")

    async def get_hosts(self, host_groups: list[str] | None = None) -> HostList:
        """Return all hosts with their update counters.

        ``host_groups`` filters by group IDs or names (PatchMon matches
        either); an empty list or ``None`` returns every host.
        """
        params = {"include": "stats"}
        if host_groups:
            params["hostgroup"] = ",".join(host_groups)
        body = await self._get("/hosts", params)
        hosts = body.get("hosts") if isinstance(body, Mapping) else None
        if not isinstance(hosts, list):
            raise PatchMonUnsupportedError("No host list in the answer")
        return HostList(
            (Host.from_api(item) for item in hosts), total=_opt_int(body, "total")
        )

    async def get_host_system(self, host_id: str) -> HostSystem:
        """Return kernel, reboot and boot details of one host."""
        body = await self._get(_host_path(host_id, "system"))
        if not isinstance(body, Mapping):
            raise PatchMonUnsupportedError("System details are not an object")
        return HostSystem.from_api(body)

    async def get_host_info(self, host_id: str) -> HostInfo:
        """Return agent details of one host."""
        body = await self._get(_host_path(host_id, "info"))
        if not isinstance(body, Mapping):
            raise PatchMonUnsupportedError("Host info is not an object")
        return HostInfo.from_api(body)

    async def get_host_packages(
        self, host_id: str, *, updates_only: bool = True
    ) -> list[Package]:
        """Return the packages of one host, by default only those with updates."""
        params = {"updates_only": "true"} if updates_only else None
        body = await self._get(_host_path(host_id, "packages"), params)
        packages = body.get("packages") if isinstance(body, Mapping) else None
        if not isinstance(packages, list):
            raise PatchMonUnsupportedError("No package list in the answer")
        return [
            Package.from_api(item) for item in packages if isinstance(item, Mapping)
        ]
