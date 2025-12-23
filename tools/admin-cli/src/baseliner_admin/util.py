from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any


def try_parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except Exception:
        return None


def read_json_file(path: Path) -> Any:
    data = path.read_text(encoding="utf-8")
    return json.loads(data)
