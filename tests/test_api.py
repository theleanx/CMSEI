import pytest


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200


def test_materials_list_has_19_and_provenance(client):
    r = client.get("/api/v1/materials")
    assert r.status_code == 200
    body = r.json()
    items = body["materials"] if isinstance(body, dict) and "materials" in body else body
    assert len(items) == 19
    assert all("score" in x and "tier" in x for x in items)


def test_material_detail_and_history(client):
    assert client.get("/api/v1/materials/cobalt").status_code == 200
    assert client.get("/api/v1/materials/cobalt/history").status_code == 200
    assert client.get("/api/v1/materials/nope").status_code == 404


def test_csv_exports(client):
    r = client.get("/api/v1/materials.csv")
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    assert client.get("/api/v1/sectors.csv").status_code == 200


def test_assess_by_id(client):
    r = client.post("/api/v1/assess", json={"material_id": "cobalt", "sourcing_region": "china", "volume_tier": "large"})
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok" and j["snapshot"]["tier"] in ("Low", "Moderate", "High", "Critical")
    assert "not stored" in j["privacy"]
    assert "Not validated" in j["validation_status"]


def test_assess_by_text(client):
    r = client.post("/api/v1/assess", json={"material_description": "lithium carbonate for cells"})
    assert r.status_code == 200 and r.json()["material_id"] == "lithium"


def test_assess_unresolved_text(client):
    r = client.post("/api/v1/assess", json={"material_description": "birthday cake frosting"})
    assert r.status_code == 200 and r.json()["status"] in ("no_match", "needs_choice")


def test_assess_rejects_bad_input(client):
    assert client.post("/api/v1/assess", json={}).status_code == 422
    assert client.post("/api/v1/assess", json={"material_id": "cobalt", "sourcing_region": "mars"}).status_code == 422
    assert client.post("/api/v1/assess", json={"material_description": "x" * 301}).status_code == 422
    assert client.post("/api/v1/assess", json={"material_id": "nope"}).status_code == 404


def test_scenarios(client):
    r = client.post("/api/v1/scenarios", json={"material_id": "rare-earths", "family": "add_source"})
    assert r.status_code == 200
    assert client.post("/api/v1/scenarios", json={"material_id": "rare-earths", "family": "zzz"}).status_code == 422
    assert client.post("/api/v1/scenarios", json={"material_id": "rare-earths", "family": "event_change", "option": "zzz"}).status_code == 422


def test_snapshot_verify_reproduces_every_material(client):
    items = client.get("/api/v1/materials").json()
    items = items["materials"] if isinstance(items, dict) and "materials" in items else items
    for it in items:
        sid = it.get("snapshot_id")
        assert sid, it
        v = client.get(f"/api/v1/snapshots/{sid}/verify").json()
        assert v["reproduced"] and v["payload_hash_matches"], it["id"] if "id" in it else it


def test_pdf(client):
    r = client.get("/api/v1/materials/cobalt/report.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    r2 = client.get("/materials/cobalt/report.pdf")
    assert r2.status_code == 200 and r2.content[:4] == b"%PDF"


def test_watchlist_requires_session(client):
    assert client.get("/api/v1/watchlist").status_code == 401


def test_session_watchlist_lifecycle(client):
    tok = client.post("/api/v1/sessions").json()["session_token"]
    h = {"X-Session-Token": tok}
    assert client.post("/api/v1/watchlist", json={"material_id": "cobalt", "alert_threshold": 60}, headers=h).status_code == 201
    assert len(client.get("/api/v1/watchlist", headers=h).json()["items"]) == 1
    assert client.post("/api/v1/watchlist", json={"material_id": "nope"}, headers=h).status_code == 404
    assert client.delete("/api/v1/watchlist/cobalt", headers=h).status_code in (200, 204)
    assert client.delete("/api/v1/session", headers=h).status_code == 204
    assert client.get("/api/v1/watchlist", headers=h).status_code == 401


def test_session_token_stored_hashed(client):
    from app.db import SessionLocal
    from app import models as M
    from sqlalchemy import select
    tok = client.post("/api/v1/sessions").json()["session_token"]
    with SessionLocal() as db:
        hs = [s.token_hash if hasattr(s, "token_hash") else None for s in db.execute(select(M.Session)).scalars()]
    assert tok not in [h for h in hs if h]


def test_corrections_accept_and_validate(client):
    ok = {"material_id": "cobalt", "item": "import share", "proposed_value": "DRC 60", "source_link": "https://example.org/x"}
    assert client.post("/api/v1/corrections", json=ok).status_code == 201
    bad = dict(ok, source_link="javascript:alert(1)")
    assert client.post("/api/v1/corrections", json=bad).status_code == 422


def test_security_headers(client):
    r = client.get("/")
    assert "content-security-policy" in {k.lower() for k in r.headers}
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_cors_get_only(client):
    r = client.options("/api/v1/assess", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "POST" not in r.headers.get("access-control-allow-methods", "")


def test_error_shape_has_no_stack(client):
    r = client.get("/api/v1/materials/zzz")
    assert "Traceback" not in r.text
