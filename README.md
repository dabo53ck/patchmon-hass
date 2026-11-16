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

> **Work in progress.** This is an early development version. Setup works;
> devices, entities and actions follow in the next steps towards v0.1.0.

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
| Server address | `http://192.168.1.10:3000` |
| Token key / secret | from the token you created above |
| Verify SSL certificate | turn off only for a self-signed certificate |

Options (polling interval, host group filter) are under **Configure** on the
integration entry. If the token is changed or expires, Home Assistant asks for
a new one; **Reconfigure** changes the address without losing anything.

## License

[MIT](LICENSE)
