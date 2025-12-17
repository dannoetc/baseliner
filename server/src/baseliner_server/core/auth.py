from __future__ import annotations

"""Auth helpers (re-exported for clean import paths).

Historically we kept FastAPI dependency helpers under `baseliner_server.api.deps`.
Some modules/scripts referenced `baseliner_server.core.auth`; this module keeps that
import path stable by re-exporting the canonical helpers.

Keep this file *thin* and avoid importing server app objects to prevent import cycles.
"""

from baseliner_server.api.deps import get_current_device, require_admin

__all__ = [
    "get_current_device",
    "require_admin",
]
