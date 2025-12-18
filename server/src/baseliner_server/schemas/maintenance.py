from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PruneRequest(BaseModel):
    keep_days: int = 30
    keep_runs_per_device: int = 200
    dry_run: bool = True
    batch_size: int = 500

    # NEW: optionally prune a single device
    device_id: str | None = None


class PruneCounts(BaseModel):
    runs: int = 0
    run_items: int = 0
    log_events: int = 0


class PruneResponse(BaseModel):
    dry_run: bool
    keep_days: int
    keep_runs_per_device: int
    cutoff: datetime

    runs_targeted: int
    counts: PruneCounts

    notes: dict[str, Any] = Field(default_factory=dict)
