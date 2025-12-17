"""Compatibility module.

Some earlier drafts/imports referenced ``baseliner_server.core.db.get_db``.
The dependency provider actually lives in :mod:`baseliner_server.api.deps`.

Keeping this shim avoids churn across the server + tests while we settle
on the final module layout.
"""

from __future__ import annotations

from baseliner_server.api.deps import get_db

__all__ = ["get_db"]
