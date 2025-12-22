# baseliner-admin (CLI)

A CLI-first operator/developer tool for administering a Baseliner server.

This is intentionally **CLI first** (not a full-screen TUI yet) so we can iterate quickly on the API contract.

## Install (editable)

From repo root:

```bash
pip install -e ./tools/admin-cli
```

## Configure

You can pass flags per command, or set environment variables:

- `BASELINER_SERVER_URL` (default: `http://localhost:8000`)
- `BASELINER_ADMIN_KEY` (required)

## Examples

List devices:

```bash
baseliner-admin --server http://localhost:8000 devices list
```

Show debug bundle for a device:

```bash
baseliner-admin devices show <device-uuid>
```

Soft delete a device:

```bash
baseliner-admin devices delete <device-uuid> --reason "testing"
```

Restore a device (prints new token):

```bash
baseliner-admin devices restore <device-uuid>
```

Revoke token (prints new token):

```bash
baseliner-admin devices revoke-token <device-uuid>
```

Tail audit:

```bash
baseliner-admin audit tail --limit 20
baseliner-admin audit tail --action device.delete
```

Assign policy (by device key; will look up the device id via admin list):

```bash
baseliner-admin assign set --device-key DESKTOP-FTVVO4A --policy-name baseliner-windows-core --mode enforce
```

## Notes

- `--json` prints raw JSON instead of tables.
- This tool calls the server admin API (`/api/v1/admin/*`).
