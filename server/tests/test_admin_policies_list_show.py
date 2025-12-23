from __future__ import annotations

from baseliner_server.db.models import Policy


def _mk_policy(name: str, *, active: bool, description: str | None = None) -> Policy:
    return Policy(
        name=name,
        description=description,
        schema_version="1.0",
        document={"schema_version": "1", "resources": []},
        is_active=bool(active),
    )


def test_admin_policies_list_default_excludes_inactive(client, db):
    p1 = _mk_policy("alpha", active=True, description="aaa")
    p2 = _mk_policy("beta", active=False, description="bbb")
    db.add_all([p1, p2])
    db.commit()

    resp = client.get("/api/v1/admin/policies?limit=200&offset=0")
    assert resp.status_code == 200
    body = resp.json()
    names = [p["name"] for p in body["items"]]
    assert "alpha" in names
    assert "beta" not in names


def test_admin_policies_list_include_inactive(client, db):
    p1 = _mk_policy("alpha", active=True)
    p2 = _mk_policy("beta", active=False)
    db.add_all([p1, p2])
    db.commit()

    resp = client.get("/api/v1/admin/policies?include_inactive=true&limit=200&offset=0")
    assert resp.status_code == 200
    body = resp.json()
    names = [p["name"] for p in body["items"]]
    assert "alpha" in names
    assert "beta" in names


def test_admin_policies_list_q_filters(client, db):
    p1 = _mk_policy("chrome-policy", active=True, description="browser")
    p2 = _mk_policy("firefox-policy", active=True, description="browser")
    p3 = _mk_policy("windows-core", active=True, description="os baseline")
    db.add_all([p1, p2, p3])
    db.commit()

    resp = client.get("/api/v1/admin/policies?q=fire&limit=200&offset=0")
    assert resp.status_code == 200
    body = resp.json()
    names = [p["name"] for p in body["items"]]
    assert "firefox-policy" in names
    assert "chrome-policy" not in names
    assert "windows-core" not in names


def test_admin_policies_show(client, db):
    p = _mk_policy("alpha", active=True, description="hello")
    db.add(p)
    db.commit()

    resp = client.get(f"/api/v1/admin/policies/{p.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(p.id)
    assert body["name"] == "alpha"
    assert body["description"] == "hello"
    assert isinstance(body["document"], dict)
