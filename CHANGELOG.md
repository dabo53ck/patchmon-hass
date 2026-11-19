# Changelog

All notable changes to this project are documented here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). SemVer,
pre-release identifiers included (`0.1.0-rc.1`, …).

## [Unreleased]

### Added

- Project skeleton, CI (hassfest, HACS, Ruff, mypy, pytest) and brand assets.
- Read-only PatchMon API client for the Integration API (`host:get` scope).
- Config flow with connection test, re-authentication, reconfiguration and
  options (polling interval, host group filter, area for new devices, one
  switch per optional entity for all hosts). When reconfiguring, an empty
  token secret keeps the stored one.
- A device for the PatchMon server and one per host, linked to the host page
  in PatchMon. New hosts appear by themselves, deleted hosts are removed.
- Sensors per host: pending updates, security updates, update status, last
  check-in, restart reason, agent version, last boot, running and installed
  kernel, installed packages.
- Binary sensors per host: restart required and reporting.
- Update entity per host (disabled by default) with the package list as
  release notes.
- Totals on the server device: hosts, hosts with (security) updates, hosts
  requiring a restart, hosts not reporting, pending and security updates.
- Repair issue when a group of the host group filter has no hosts any more;
  devices are kept then instead of being removed.
- Actions `get_hosts` (hosts with their patch status, filterable),
  `get_packages` (packages of one host) and `refresh` (read PatchMon now).
- Diagnostics for the entry and every device; the server address, token,
  host names, IP addresses and machine IDs are removed.
- Repair issue when PatchMon answers in a way the integration does not
  understand; it goes away by itself once an answer is understood again.
- Marketplace category "Computers & network › Monitoring" and connectivity
  "Local network" for the Marketplace in Home Assistant 2026.11.
- Quality scale checklist (`quality_scale.yaml`).
- Debug logging: every request to PatchMon (path, status, duration), a
  summary per update (hosts listed, details read again) and added or removed
  devices; never the server address or the token.

### Fixed (since 0.1.0-rc.1)

- A 404 on the details of a host no longer removes the host and its device;
  only the host list decides that a host is gone.
- An empty host list on the first update after a restart no longer removes
  all host devices.
- A host device deleted by the user gets its entities back when the host
  returns, without reloading the entry.
- Two `refresh` actions at the same time both get the details they asked for.
- A wrong address that answers 404 is shown as "did not answer like a
  PatchMon server" instead of "unexpected error" with a traceback in the log.
- Deleting a host device while the entry is not loaded (server unreachable)
  no longer fails.
- Connection and certificate errors no longer contain the server address or
  IP address (aiohttp puts them into its messages).
