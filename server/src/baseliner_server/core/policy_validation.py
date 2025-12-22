from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PolicyDocError:
    path: str
    message: str


class PolicyDocValidationError(Exception):
    def __init__(self, errors: list[PolicyDocError]) -> None:
        super().__init__("policy document validation failed")
        self.errors = errors


def validate_and_normalize_document(document: Any) -> dict[str, Any]:
    """
    Validate + normalize a policy document.

    Normalization rules (MVP):
      - document must be dict (or None => {"resources": []})
      - document.resources must be a list (or missing/None => [])
      - resource.type is required; normalized to lowercase
      - resource.id is required; normalized to lowercase
          - for winget.package: if id missing but package_id exists -> id = package_id.lower()

    Known-type validation (MVP):
      - winget.package requires package_id; ensure in {"present","absent"} (default: present)
      - script.powershell requires script or path; timeout_seconds if present must be int > 0
    """
    if document is None:
        return {"resources": []}

    if not isinstance(document, dict):
        raise PolicyDocValidationError([PolicyDocError("document", "must be an object")])

    raw_resources = document.get("resources", [])
    if raw_resources is None:
        raw_resources = []

    errors: list[PolicyDocError] = []

    if not isinstance(raw_resources, list):
        raise PolicyDocValidationError([PolicyDocError("document.resources", "must be a list")])

    out_doc: dict[str, Any] = dict(document)
    out_resources: list[dict[str, Any]] = []

    for i, r in enumerate(raw_resources):
        pfx = f"document.resources[{i}]"

        if not isinstance(r, dict):
            errors.append(PolicyDocError(pfx, "must be an object"))
            continue

        nr: dict[str, Any] = dict(r)

        rtype = str(nr.get("type") or "").strip().lower()
        if not rtype:
            errors.append(PolicyDocError(f"{pfx}.type", "is required"))
            out_resources.append(nr)
            continue

        nr["type"] = rtype

        rid = nr.get("id")
        rid_str = str(rid).strip().lower() if rid is not None else ""

        # Auto-fill id for winget.package if missing and package_id is present
        if not rid_str and rtype == "winget.package":
            pkg = nr.get("package_id") or nr.get("packageId")
            if pkg:
                rid_str = str(pkg).strip().lower()

        if not rid_str:
            errors.append(PolicyDocError(f"{pfx}.id", "is required"))
        else:
            nr["id"] = rid_str

        # Normalize ensure (if present)
        if "ensure" in nr and nr["ensure"] is not None:
            nr["ensure"] = str(nr["ensure"]).strip().lower()

        # ---- Type-specific validation ----
        if rtype == "winget.package":
            # accept packageId legacy
            pkg = nr.get("package_id") or nr.get("packageId")
            if not pkg or not str(pkg).strip():
                errors.append(PolicyDocError(f"{pfx}.package_id", "is required for winget.package"))
            else:
                nr["package_id"] = str(pkg).strip()
                if "packageId" in nr:
                    del nr["packageId"]

            ensure = str(nr.get("ensure") or "present").strip().lower()
            if ensure not in ("present", "absent"):
                errors.append(PolicyDocError(f"{pfx}.ensure", "must be 'present' or 'absent'"))
            nr["ensure"] = ensure

        elif rtype == "script.powershell":
            # allow inline script or filesystem path
            script = nr.get("script")
            path = nr.get("path")
            if (not script or not str(script).strip()) and (not path or not str(path).strip()):
                errors.append(PolicyDocError(pfx, "script.powershell requires 'script' or 'path'"))

            # normalize timeout_seconds (accept timeoutSeconds)
            ts = nr.get("timeout_seconds", nr.get("timeoutSeconds"))
            if ts is not None:
                try:
                    ts_i = int(ts)
                    if ts_i <= 0:
                        raise ValueError()
                    nr["timeout_seconds"] = ts_i
                except Exception:
                    errors.append(
                        PolicyDocError(f"{pfx}.timeout_seconds", "must be a positive integer")
                    )
                if "timeoutSeconds" in nr:
                    del nr["timeoutSeconds"]

        # Unknown types: keep as-is (MVP), only require type/id.
        out_resources.append(nr)

    out_doc["resources"] = out_resources

    if errors:
        raise PolicyDocValidationError(errors)

    return out_doc
