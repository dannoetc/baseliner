# baseliner-admin (CLI)

A CLI-first operator/developer tool for administering a Baseliner server.

This intentionally starts as **CLI-first** so we can iterate quickly on the API contract and
operator workflow.

An experimental, prompt-driven TUI is also available via `baseliner-admin tui`.

## Install (editable)

From repo root:

```bash
pip install -e ./tools/admin-cli
```

## Configure

The CLI reads config from env vars (or flags):

- `BASELINER_SERVER_URL` (example: `http://localhost:8000`)
- `BASELINER_ADMIN_KEY` (your admin key)

## Examples

```bash
baseliner-admin devices list
baseliner-admin devices debug <device-uuid>
baseliner-admin devices delete <device-uuid> --reason "decommission"
baseliner-admin devices restore <device-uuid>
baseliner-admin devices revoke-token <device-uuid>

baseliner-admin runs list --limit 25
baseliner-admin runs show <run-uuid> --full

baseliner-admin policies list
baseliner-admin policies find firefox
baseliner-admin policies show baseliner-windows-core
baseliner-admin policies show 00000000-0000-0000-0000-000000000000
baseliner-admin policies upsert ./policies/baseliner-windows-core.json

# Experimental TUI (prompt-driven)
baseliner-admin tui


baseliner-admin assignments list <device-ref>
baseliner-admin assignments set <device-ref> <policy-ref> --priority 100 --mode enforce
baseliner-admin assignments update <device-ref> <policy-ref> --priority 50 --mode audit
baseliner-admin assignments remove <device-ref> <policy-ref>
baseliner-admin assignments clone <src-device-ref> <dst-device-ref> --clear-first --priority-offset 0
baseliner-admin assignments apply <device-ref> ./assignments.json --merge --plan
baseliner-admin assignments apply <device-ref> ./assignments.json --yes
baseliner-admin assignments clear <device-ref>
```

### Bulk apply assignments from a file

Use this to "bulk set" assignments for a device from a JSON file.

```bash
baseliner-admin assignments apply <device-ref> ./assignments.json --plan
baseliner-admin assignments apply <device-ref> ./assignments.json --merge
baseliner-admin assignments apply <device-ref> ./assignments.json --clear-first
```

File formats supported:

- A JSON list of assignment objects
- Or an object with an `assignments` key containing that list

Each assignment object accepts:

- `policy`: policy name, UUID, or substring (must resolve uniquely)
- `mode`: `enforce` or `audit` (default: `enforce`)
- `priority`: integer (default: `100`)

Example:

```json
{
  "assignments": [
    {"policy": "baseliner-windows-core", "mode": "enforce", "priority": 100},
    {"policy": "firefox", "mode": "audit", "priority": 200}
  ]
}
```

Behavior:

- Default: **sync** to the file (adds/updates desired assignments and removes assignments not present)
- `--merge`: add/update only; do **not** remove extras
- `--clear-first`: clears all current assignments, then sets those in the file


## Notes

- This tool is intentionally lightweight and relies on the server for pagination and filtering.
- For machine output, add `--json` to most commands.

## Experimental: TUI

Run:

```bash
baseliner-admin tui
```

Notes:

- This is **experimental** and intentionally conservative: it uses prompts + tables (not a full
  arrow-key interface) so we can iterate safely.
- Destructive actions (delete device / revoke token) always ask for confirmation.
