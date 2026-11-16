# Changelog

All notable changes to this project are documented here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). SemVer,
pre-release identifiers included (`0.1.0-rc.1`, …).

## [Unreleased]

### Added

- Project skeleton, CI (hassfest, HACS, Ruff, mypy, pytest) and brand assets.
- Read-only PatchMon API client for the Integration API (`host:get` scope).
- Config flow with connection test, re-authentication, reconfiguration and
  options (polling interval, host group filter).
