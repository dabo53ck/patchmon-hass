# Changelog

All notable changes to this project are documented here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). SemVer,
pre-release identifiers included (`0.1.0-rc.1`, …).

## [Unreleased]

### Added

- Project skeleton, CI (hassfest, HACS, Ruff, mypy, pytest) and brand assets.
- Read-only PatchMon API client for the Integration API (`host:get` scope).
- Config flow with connection test, re-authentication, reconfiguration and
  options (polling interval, host group filter, area for new devices). When
  reconfiguring, an empty token secret keeps the stored one.
- A device for the PatchMon server and one per host, linked to the host page
  in PatchMon. New hosts appear by themselves, deleted hosts are removed.
- Sensors per host: pending updates, security updates, update status, last
  check-in, agent version, last boot, running and installed kernel,
  installed packages.
- Binary sensors per host: restart required (with the reason) and reporting.
- Update entity per host (disabled by default) with the package list as
  release notes.
- Totals on the server device: hosts, hosts with (security) updates, hosts
  requiring a restart, hosts not reporting, pending and security updates.
- Repair issue when a group of the host group filter has no hosts any more;
  devices are kept then instead of being removed.
