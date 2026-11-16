# Test fixtures

Real answers of a PatchMon 2.1.8 server (Integration API, `host:get`),
anonymised before they were committed:

- host, group and package IDs replaced by fixed fake UUIDs
- host names → `host-01` … `host-04`, display names → `Host 01` …
- group names → `auto-updates`, `security-only`
- IP addresses → `192.0.2.0/24` (documentation range)
- `machine_id` replaced, disk lists reduced to `/` with a generic device name

Package names, versions and descriptions are public Debian/Ubuntu data and
kept as they are. The four hosts cover: up to date but restart required
(kernel mismatch), security updates plus restart required, normal updates
only, and a single security update.

| File | Endpoint |
| --- | --- |
| `hosts.json` | `GET /hosts?include=stats` |
| `hosts_unknown_group.json` | `GET /hosts?hostgroup=<unknown>` |
| `host_NN_system.json` | `GET /hosts/{id}/system` |
| `host_NN_info.json` | `GET /hosts/{id}/info` |
| `host_NN_packages.json` | `GET /hosts/{id}/packages?updates_only=true` |
| `error_401.json`, `error_404.json` | error bodies |
