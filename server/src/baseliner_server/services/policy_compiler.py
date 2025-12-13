import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from baseliner_server.db.models import Policy, PolicyAssignment


def _stable_hash(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compile_effective_policy(db: Session, device_id) -> dict[str, Any]:
    """
    MVP compiler:
    - Pull all active policies assigned to device ordered by priority asc (lowest number = highest precedence).
    - Merge resources with first-wins by (type,id) so higher precedence wins.
    - Compute effectivePolicyHash over compiled document.
    - Compute effective mode: "audit" only if *all* assignments are audit; otherwise "enforce".
    """
    stmt = (
        select(PolicyAssignment, Policy)
        .join(Policy, Policy.id == PolicyAssignment.policy_id)
        .where(PolicyAssignment.device_id == device_id)
        .where(Policy.is_active == True)  # noqa: E712
        .order_by(PolicyAssignment.priority.asc())
    )
    rows = db.execute(stmt).all()

    if not rows:
        doc = {"schemaVersion": "1.0", "policyId": "compiled", "name": "Compiled Policy", "resources": []}
        return {
            "policy_id": None,
            "policy_name": None,
            "schema_version": "1.0",
            "mode": "enforce",
            "document": doc,
            "effective_policy_hash": _stable_hash(doc),
            "sources": [],
        }

    sources: list[dict[str, Any]] = []
    all_audit = True

    # First-wins map by (type,id)
    merged: dict[tuple[str, str], dict[str, Any]] = {}

    for assignment, policy in rows:
        mode = getattr(assignment.mode, "value", str(assignment.mode))
        if mode != "audit":
            all_audit = False

        sources.append(
            {
                "policy_id": str(policy.id),
                "policy_name": policy.name,
                "priority": assignment.priority,
                "mode": mode,
            }
        )

        pdoc = policy.document or {}
        resources = pdoc.get("resources", []) or []

        for res in resources:
            rtype = str(res.get("type", "")).strip()
            rid = str(res.get("id", "")).strip()
            if not rtype or not rid:
                continue

            key = (rtype, rid)
            if key not in merged:
                merged[key] = res  # first-wins => higher precedence (lower priority number) wins

    compiled_doc = {
        "schemaVersion": "1.0",
        "policyId": "compiled",
        "name": "Compiled Policy",
        "resources": list(merged.values()),
        "sources": sources,  # handy for debugging
    }

    return {
        "policy_id": "compiled",
        "policy_name": "Compiled Policy",
        "schema_version": "1.0",
        "mode": "audit" if all_audit else "enforce",
        "document": compiled_doc,
        "effective_policy_hash": _stable_hash(compiled_doc),
        "sources": sources,
    }
