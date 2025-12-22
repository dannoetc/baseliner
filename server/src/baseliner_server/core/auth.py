from __future__ import annotations

from baseliner_server.api.deps import get_current_device, require_admin

"""Auth helpers (re-exported for clean import paths).

Historically we kept FastAPI dependency helpers under `baseliner_server.api.deps`.
Some modules/scripts referenced `baseliner_server.core.auth`; this module keeps that
import path stable by re-exporting the canonical helpers.

Keep this file *thin* and avoid importing server app objects to prevent import cycles.
"""


__all__ = [
    "get_current_device",
    "require_admin",
]
