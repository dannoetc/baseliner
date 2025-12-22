# Policy resolution

Placeholder for effective policy compilation.

## Current semantics (MVP)

- Assignments are ordered by ascending `priority` (lower = higher priority)
- Resource conflicts are resolved by “first wins” on `(resource_type, resource_id)`

## TODO

- Document compilation metadata returned to the device
- Document hashing strategy for effective policy
