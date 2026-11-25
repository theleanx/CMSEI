import re
from .conftest import csrf_of


def post(c, url, data):
    data = dict(data, csrf=csrf_of(c))
    return c.post(url, data=data, follow_redirects=False)


def test_assess_requires_csrf(fresh):
    r = fresh.post("/assess", data={"material_id": "cobalt"})
    assert r.status_code == 403


def test_assess_dropdown_renders_result(fresh):
    r = post(fresh, "/assess", {"material_id": "cobalt", "sourcing_region": "china", "volume_tier": "large"})
    assert r.status_code == 200
    assert "Cobalt" in r.text and re.search(r"\b(Low|Moderate|High|Critical)\b", r.text)
    assert "validation" in r.text.lower() or "validated" in r.text.lower()


def test_assess_text(fresh):
    r = post(fresh, "/assess", {"material_description": "tantalum capacitors"})
    assert r.status_code == 200 and "Tantalum" in r.text


def test_assess_unresolved_asks_to_choose(fresh):
    r = post(fresh, "/assess", {"material_description": "birthday cake"})
    assert r.status_code == 200 and "<select" in r.text


def test_assess_empty_is_422(fresh):
    assert post(fresh, "/assess", {}).status_code == 422


def test_simulate_marks_result_as_simulation(fresh):
    r = post(fresh, "/materials/rare-earths/simulate", {"family": "add_source"})
    assert r.status_code == 200 and "imulat" in r.text
    assert post(fresh, "/materials/rare-earths/simulate", {"family": "bogus"}).status_code == 422


def test_watchlist_cycle(fresh):
    r = post(fresh, "/watchlist/add", {"material_id": "cobalt"})
    assert r.status_code == 303 and "mse_session" in fresh.cookies
    assert "Cobalt" in fresh.get("/watchlist").text
    assert post(fresh, "/watchlist/seen", {}).status_code == 303
    assert post(fresh, "/watchlist/remove", {"material_id": "cobalt"}).status_code == 303
    assert "Cobalt" not in fresh.get("/watchlist").text.split("<main")[1]


def test_session_delete_clears_everything(fresh):
    post(fresh, "/watchlist/add", {"material_id": "tin"})
    r = post(fresh, "/session/delete", {})
    assert r.status_code == 303
    from app.db import SessionLocal
    from app import models as M
    from sqlalchemy import select
    with SessionLocal() as db:
        assert db.execute(select(M.Watchlist).where(M.Watchlist.material_id == "tin")).first() is None


def test_unknown_material_page_404(fresh):
    assert fresh.get("/materials/zzz").status_code == 404


def test_xss_in_text_is_not_reflected_raw(fresh):
    r = post(fresh, "/assess", {"material_description": "<script>alert(1)</script>"})
    assert "<script>alert(1)</script>" not in r.text


def test_pages_have_banner_and_status(fresh):
    r = fresh.get("/")
    assert "preview" in r.text.lower()
    assert "shadow" in fresh.get("/status").text.lower() or "shadow" in fresh.get("/methodology").text.lower()


def test_admin_requires_auth(fresh):
    assert fresh.get("/admin").status_code in (401, 403, 404)
    r = fresh.get("/admin", auth=("admin", "wrong"))
    assert r.status_code in (401, 403)
    ok = fresh.get("/admin", auth=("admin", "test-admin-pw"))
    assert ok.status_code == 200
