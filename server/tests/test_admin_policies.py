from __future__ import annotations


def test_admin_policies_list_and_show(client):
    # Create active policy
    p1 = {
        "name": "windows-core",
        "description": "core hardening",
        "schema_version": "1.0",
        "document": {"resources": []},
        "is_active": True,
    }
    r = client.post("/api/v1/admin/policies", json=p1)
    assert r.status_code == 200
    policy_id_1 = r.json()["policy_id"]

    # Create inactive policy
    p2 = {
        "name": "windows-legacy",
        "description": "legacy",
        "schema_version": "1.0",
        "document": {"resources": []},
        "is_active": False,
    }
    r = client.post("/api/v1/admin/policies", json=p2)
    assert r.status_code == 200
    policy_id_2 = r.json()["policy_id"]

    # Default list => active only
    r = client.get("/api/v1/admin/policies")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == policy_id_1

    # Include inactive => both
    r = client.get("/api/v1/admin/policies?include_inactive=true")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    ids = {it["id"] for it in body["items"]}
    assert ids == {policy_id_1, policy_id_2}

    # Substring match => only matching (case-insensitive)
    r = client.get("/api/v1/admin/policies?include_inactive=true&q=LEG")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == policy_id_2

    # Show policy details
    r = client.get(f"/api/v1/admin/policies/{policy_id_1}")
    assert r.status_code == 200
    d = r.json()
    assert d["id"] == policy_id_1
    assert d["name"] == "windows-core"
    assert d["document"] == {"resources": []}
