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
| Optional entities | one switch each for updates, running kernel, installed kernel and installed packages on every host |

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

Each PatchMon server can be added once. Setup recognises the same server
under a second address (IP and name, LAN and reverse proxy) by its hosts and
stops; use **Reconfigure** on the existing entry to switch it to the new
address instead.

## Devices and entities

The PatchMon server is a device of its own; every host is a device linked to
it, with a link to the host page in PatchMon. Hosts added in PatchMon appear by
themselves, hosts deleted in PatchMon are removed together with their entities.
Only the host list decides that a host is gone: if it is suddenly empty (also
right after a restart), nothing is removed. A host device you delete yourself
gets its entities back when PatchMon lists the host again.

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
**Skip** hides only the label shown at that moment: once the number of
updates changes, the update shows up again.
The update entity is disabled by default so that many hosts do not crowd the
update list in the Home Assistant settings; enable it per host if you want it.

### Host group filter

With a host group filter, only hosts of the selected groups are added. If a
selected group has no hosts in PatchMon any more (deleted or emptied),
Home Assistant shows a repair issue and keeps the devices of those hosts as
unavailable instead of removing them. Update the filter under **Configure**.

## Actions

All actions only read; none of them changes anything in PatchMon.

| Action | What it does |
| --- | --- |
| `patchmon_hass.get_hosts` | Returns the hosts with their patch status as of the last update, without asking PatchMon. Optional filters: PatchMon server, update status, restart required, reporting. |
| `patchmon_hass.get_packages` | Reads the packages of one host from PatchMon and returns them, security updates first. Options: only with updates (default on), only security updates, limit (default 50), include descriptions (default off, makes the answer much longer). |
| `patchmon_hass.refresh` | Reads the host list and the host details from PatchMon now, for all hosts or the selected devices. It does **not** make the agents report: values only change after their next check-in. |

`get_hosts` returns for each host the name it has in Home Assistant (your own
name if you renamed the device), PatchMon's name as `patchmon_name`, the device
ID, the server, the operating system, update status, pending and security
updates, whether a restart is required and why, the reporting state, the last
check-in and the agent version.

## How data is updated

- The host list with the update counters is read every 5 minutes (1 to 60,
  under **Configure**).
- Kernel, restart reason, last boot and agent version are read for a host only
  when its agent has reported again since, and at least every 6 hours.
- The package list is read only when you open the release notes of an update
  entity or call `get_packages`.
- PatchMon itself only knows what the agents report, on their own schedule.

## Examples

Notify when a host needs security updates:

```yaml
triggers:
  - trigger: numeric_state
    entity_id: sensor.patchmon_hosts_with_security_updates
    above: 0
actions:
  - action: patchmon_hass.get_hosts
    data:
      update_status: security_required
    response_variable: result
  - action: notify.notify
    data:
      title: Security updates
      message: >
        {{ result.hosts | map(attribute='name') | join(', ') }}
```

A script for a voice assistant ("Which servers need a restart?"):

```yaml
sequence:
  - action: patchmon_hass.get_hosts
    data:
      restart_required: true
    response_variable: result
  - stop: done
    response_variable: result
```

## Troubleshooting

- **Repair "answer from PatchMon not understood":** the server answered in a
  way the integration does not understand, for example because the address
  points to the web interface behind a proxy or the PatchMon version is not
  supported yet. Check the address with **Reconfigure**. The repair goes away
  by itself once an answer is understood again.
- **"The address redirects to another one":** the address answers with a
  redirect, typically from `http://` to `https://` or to the login page of a
  proxy. Redirects are not followed, so the token never goes to another
  address; enter the address PatchMon answers on directly.
- **Token rejected:** Home Assistant asks for a new token (re-authentication).
  Check that the token is enabled, not expired, has `host:get` and, if
  restricted, allows the IP address of Home Assistant.
- **Diagnostics:** the integration entry and every device offer **Download
  diagnostics**. The server address, the token, host names, IP addresses and
  machine IDs are removed from the file.
- **Debug logging:** enable it on the integration entry, or add
  `custom_components.patchmon_hass: debug` under `logger:` → `logs:` in
  `configuration.yaml`. The log then shows every request to PatchMon (path,
  HTTP status, duration), how many hosts were listed, which hosts had their
  details read again and why (no details yet, reported again, older than six
  hours, refresh action), and which devices were added or removed. Host names
  appear in it. The integration's own messages never contain the server
  address or the token, but lines from Home Assistant itself show the entry
  title, which contains the address; check before sharing.

## Known limitations

- Read-only: no updates can be installed or approved from Home Assistant.
- Values are only as fresh as the last agent report; `refresh` cannot change
  that.
- PatchMon has no version number for a whole host, so the update entity shows
  labels instead of versions.
- Only PatchMon 2.x is supported (tested with 2.1.8).
- No push yet: changes arrive with the next poll.

## Removal

1. **Settings → Devices & services → PatchMon** → three-dot menu →
   **Delete**. This removes all devices and entities of that server.
2. Optional: uninstall **PatchMon** in HACS and restart Home Assistant.
3. Delete the API token in PatchMon (**Settings → Integrations → Scoped
   Credentials**).

## License

[MIT](LICENSE)
