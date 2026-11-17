<p align="center">
  <img src="custom_components/patchmon_hass/brand/logo.png" alt="patchmon-hass" height="96">
</p>

# PatchMon for Home Assistant

[![Validate](https://github.com/dabo53ck/patchmon-hass/actions/workflows/validate.yml/badge.svg)](https://github.com/dabo53ck/patchmon-hass/actions/workflows/validate.yml)
[![Tests](https://github.com/dabo53ck/patchmon-hass/actions/workflows/tests.yml/badge.svg)](https://github.com/dabo53ck/patchmon-hass/actions/workflows/tests.yml)

An unofficial, **read-only** Home Assistant integration for
[PatchMon](https://github.com/PatchMon/PatchMon): see the patch status of every
host PatchMon monitors (pending and security updates, required restarts,
agent check-ins) in Home Assistant.

> **Work in progress.** This is an early development version towards v0.1.0.

This project is not affiliated with or endorsed by the PatchMon project.

## Read-only by design

The integration only uses the official PatchMon Integration API with the
`host:get` permission. It never patches hosts, approves updates or deletes
anything, and it never asks for more than `host:get`.

## Requirements

- Home Assistant 2026.9.0 or newer
- PatchMon 2.x server reachable from Home Assistant

## Create an API token in PatchMon

Create a dedicated token for Home Assistant, so you can revoke it on its own:

1. In PatchMon, open **Settings → Integrations → Scoped Credentials**.
2. Create a new token and give it only the **`host:get`** permission.
   Never grant `host:delete`.
3. Optional: restrict the token to the IP address of your Home Assistant.
4. Copy the token key and secret. PatchMon shows the secret only once.

## Installation

Until the integration is in the HACS default store, add it as a custom
repository:

1. HACS → three-dot menu → **Custom repositories**.
2. Repository `https://github.com/dabo53ck/patchmon-hass`, type **Integration**.
3. Install **PatchMon**, then restart Home Assistant.

## Setup

**Settings → Devices & services → Add integration → PatchMon**, then enter:

| Field | Example |
| --- | --- |
| Server address | `http://192.168.1.10:3000` or `https://patchmon.example.com` |
| Token key / secret | from the token you created above |
| Verify SSL certificate | only applies to https; turn off for a self-signed certificate |
| Area | optional: new hosts and the server device are placed in this area |

The area only applies when a device is added, so devices you move later stay
where you put them.

Options (polling interval, host group filter, area, optional entities) are
under **Configure** on the integration entry. The four entities that are
disabled by default (updates, running kernel, installed kernel, installed
packages) each have a switch there: switching it enables or disables that
entity on every host, and new hosts get it as the switch says. Single
entities can still be switched by hand afterwards. If the token is changed or expires, Home Assistant
asks for a new one; **Reconfigure** changes the address or token without
losing anything (leave the secret empty to keep the current one).

## Devices and entities

The PatchMon server is a device of its own; every host is a device linked to
it, with a link to the host page in PatchMon. Hosts added in PatchMon appear by
themselves, hosts deleted in PatchMon are removed together with their entities.

### Per host

| Entity | Type | Notes |
| --- | --- | --- |
| Pending updates | Sensor | |
| Security updates | Sensor | |
| Update status | Sensor | Up to date, updates pending, security update required |
| Restart required | Binary sensor | |
| Restart reason | Sensor | Diagnostic; PatchMon's reason while a restart is needed, otherwise unknown |
| Reporting | Binary sensor | Off when the agent is overdue or stale (PatchMon's own limits); attribute `reporting_state` |
| Last check-in | Sensor | Diagnostic |
| Agent version | Sensor | Diagnostic |
| Last boot | Sensor | Diagnostic |
| Running kernel, installed kernel | Sensor | Diagnostic, disabled by default |
| Installed packages | Sensor | Diagnostic, disabled by default |
| Updates | Update | Disabled by default, see below |

### On the server device

Hosts, hosts with updates, hosts with security updates, hosts requiring a
restart, hosts not reporting, total pending updates, total security updates.

### The update entity

PatchMon has no version number for a whole host, so the update entity uses
labels instead of versions:

| Situation | Installed version | Latest version |
| --- | --- | --- |
| No pending updates | `current` | `current` |
| Pending updates | `current` | `16 updates` |
| Pending updates, some for security | `current` | `16 updates (1 security)` |

**Release notes** shows the packages with updates (security updates first,
at most 50). There is no install button: the integration is read-only.
The update entity is disabled by default so that many hosts do not crowd the
update list in the Home Assistant settings; enable it per host if you want it.

### Host group filter

With a host group filter, only hosts of the selected groups are added. If a
selected group has no hosts in PatchMon any more (deleted or emptied),
Home Assistant shows a repair issue and keeps the devices of those hosts as
unavailable instead of removing them. Update the filter under **Configure**.

## License

[MIT](LICENSE)
