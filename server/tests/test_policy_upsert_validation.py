from __future__ import annotations

"""Policy upsert validation + upsert semantics.

These tests protect the operator workflow:
  - invalid policy docs are rejected with structured errors
  - upsert-by-name does not create duplicates
"""


def test_policy_upsert_rejects_invalid_document(client):
    # winget.package without package_id should be rejected
    bad = {
        "name": "test-invalid-winget-missing-packageid",
        "description": "should 400",
        "schema_version": "1.0",
        "is_active": True,
        "document": {
            "resources": [
                {
                    "type": "winget.package",
                    "id": "firefox",
                    "ensure": "present",
                    # package_id intentionally omitted
                }
            ]
        },
    }

    r = client.post("/api/v1/admin/policies", json=bad)
    assert r.status_code == 400

    j = r.json()
    assert "detail" in j
    detail = j["detail"]
    # We standardize on a nested structure: {message, errors[]}
    assert isinstance(detail, dict)
    assert detail.get("message") in ("policy document invalid", "invalid policy document")

    errs = detail.get("errors")
    assert isinstance(errs, list)
    assert len(errs) >= 1
    assert "path" in errs[0] and "message" in errs[0]


def test_policy_upsert_is_idempotent_by_name(client):
    good = {
        "name": "test-valid-winget-firefox",
        "description": "first",
        "schema_version": "1.0",
        "is_active": True,
        "document": {
            "resources": [
                {
                    "type": "winget.package",
                    # allow server normalization to set id from package_id
                    "package_id": "Mozilla.Firefox",
                    "ensure": "present",
                }
            ]
        },
    }

    r1 = client.post("/api/v1/admin/policies", json=good)
    assert r1.status_code == 200
    j1 = r1.json()
    pid1 = j1.get("policy_id")
    assert pid1

    # Same name -> should update existing, not create a new policy
    good["description"] = "second"
    r2 = client.post("/api/v1/admin/policies", json=good)
    assert r2.status_code == 200
    j2 = r2.json()
    pid2 = j2.get("policy_id")
    assert pid2 == pid1
