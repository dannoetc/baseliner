from __future__ import annotations


def test_admin_policies_list_and_show(client):
    # Create two policies (one active, one inactive)
    p1 = {
        "name": "alpha-policy",
        "description": "alpha test policy",
        "schema_version": "1.0",
        "is_active": True,
        "document": {"resources": []},
    }
    p2 = {
        "name": "beta-policy",
        "description": "beta test policy",
        "schema_version": "1.0",
        "is_active": False,
        "document": {"resources": []},
    }

    r1 = client.post("/api/v1/admin/policies", json=p1)
    assert r1.status_code == 200
    r2 = client.post("/api/v1/admin/policies", json=p2)
    assert r2.status_code == 200

    # By default, list only includes active policies
    r = client.get("/api/v1/admin/policies")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert [x["name"] for x in body["items"]] == ["alpha-policy"]

    # include_inactive=true returns both
    r = client.get("/api/v1/admin/policies?include_inactive=true")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    names = sorted([x["name"] for x in body["items"]])
    assert names == ["alpha-policy", "beta-policy"]

    # substring search on name
    r = client.get("/api/v1/admin/policies?include_inactive=true&q=beta")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "beta-policy"

    # show by id returns document
    beta_id = body["items"][0]["id"]
    r = client.get(f"/api/v1/admin/policies/{beta_id}")
    assert r.status_code == 200
    detail = r.json()
    assert detail["id"] == beta_id
    assert detail["name"] == "beta-policy"
    assert isinstance(detail["document"], dict)


def test_admin_policies_show_404(client):
    r = client.get("/api/v1/admin/policies/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
