import io
import json
import datetime as dt
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app import models as M
from app.db import Base
from app.engine import bom, compliance, validation, simulator, taxonomy, scoring as sc
from app.services import alerts, company as C, snapshots as S
from .conftest import csrf_of

CSV = """product,part_number,description,supplier,minerals,annual_spend_usd,origin_country,processing_country
Motor 3kW,MTR-1,NdFeB magnet,Acme Magnetics,rare-earths,100000,China,
Motor 3kW,MTR-2,Winding wire,Copperline,,5000,,
Motor 3kW,MTR-3,Magnet B,Acme Magnetics,rare-earths,50000,,
Sensor,SNS-1,GaAs die,Waferworks,gallium; arsenic,80000,China,
Sensor,SNS-2,GaAs die B,Waferworks,gallium,20000,Japan,
Sensor,SNS-3,Tantalum capacitor,Capco,tantalum,30000,Rwanda,China
"""


@pytest.fixture()
def isolated():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=__import__("sqlalchemy.pool", fromlist=["StaticPool"]).StaticPool)
    Base.metadata.create_all(eng)
    db = sessionmaker(eng, expire_on_commit=False)()
    S.ensure_materials(db)
    S.publish_all(db)
    yield db
    db.close()


# ---------------------------------------------------------------- parsing
def test_parse_headers_and_mapping(isolated):
    p = bom.parse(CSV)
    assert len(p["rows"]) == 6
    by = {r["part"]: r for r in p["rows"]}
    assert by["MTR-1"]["minerals"] == ["rare-earths"] and by["MTR-1"]["matched_by"] == "listed"
    assert by["SNS-1"]["minerals"] == ["gallium", "arsenic"]
    assert by["MTR-2"]["minerals"] == []                       # winding wire is not a tracked material


def test_parse_sap_headers_and_description_match():
    p = bom.parse("MATNR;MAKTX;LIFNR;HERKL\nA1;tantalum capacitor 10uF;V100;CN\nA2;bolt;V200;DE\n")
    assert p["rows"][0]["minerals"] == ["tantalum"] and p["rows"][0]["matched_by"] == "description"
    assert p["rows"][0]["origin"] == "CN" and p["rows"][0]["supplier"] == "V100"
    assert bom.norm_country("CN") == "china" and bom.norm_country("PRC") == "china" and bom.norm_country("Congo (DRC)") == "democratic republic of the congo"


def test_land1_is_not_treated_as_origin():
    p = bom.parse("part_number,description,LAND1\nA1,gallium wafer,DE\n")
    assert p["rows"][0]["origin"] is None        # LAND1 is the vendor's country, not where the material came from


@pytest.mark.parametrize("bad,msg", [("", "empty"), ("a,b\n1,2\n", "part column"), ("part_number,supplier\nA,B\n", "minerals column"),
                                     ("part_number,minerals\n", "no data rows")])
def test_parse_errors_are_plain(bad, msg):
    with pytest.raises(bom.BomError) as e:
        bom.parse(bad)
    assert msg in str(e.value)


def test_row_cap(monkeypatch):
    monkeypatch.setattr(bom, "MAX_ROWS", 3)
    with pytest.raises(bom.BomError):
        bom.parse("part_number,minerals\n" + "\n".join(f"A{i},gallium" for i in range(5)))


def test_csv_formula_injection_guard():
    assert bom.safe_cell("=1+1") == "'=1+1" and bom.safe_cell("@x") == "'@x" and bom.safe_cell("ok") == "ok"


# ---------------------------------------------------------------- analysis
def test_rollup_matches_the_documented_example(isolated):
    res = C.run(isolated, CSV)
    motor = next(p for p in res["products"] if p["name"] == "Motor 3kW")
    assert motor["dependent_parts"] == 2 and motor["total_parts"] == 3 and motor["driver"] == "rare-earths"
    scores, _ = C.score_map(isolated)
    assert motor["score"] == scores["rare-earths"]["score"] and motor["tier"] == scores["rare-earths"]["tier"]
    assert res["summary"]["mapped_rows"] == 5 and res["summary"]["unmapped_rows"] == 1
    assert res["summary"]["headline"].startswith("")


def test_product_exposure_is_the_peak_of_its_parts(isolated):
    scores, _ = C.score_map(isolated)
    res = C.run(isolated, CSV)
    sensor = next(p for p in res["products"] if p["name"] == "Sensor")
    expected = max(scores[m]["composite"] for m in ("gallium", "arsenic", "tantalum"))
    assert sensor["score"] == sc.round_score(expected)


def test_origin_flags(isolated):
    res = C.run(isolated, CSV)
    flags = {p["part"]: p["origin_flag"] for p in res["parts"]}
    assert flags["MTR-1"] == "declared_dominant" and flags["MTR-3"] == "undeclared" and flags["SNS-2"] in ("declared_other", "declared_dominant")


def test_what_if_splits_direct_unknown_and_other(isolated):
    res = C.run(isolated, CSV, scenario={"material_id": "gallium", "country": "China", "cut": "full", "price_shock_pct": 20})
    x = res["scenario"]
    assert x["parts"] == {"direct": 1, "unknown": 0, "other": 1}
    assert x["cost"]["low"] == pytest.approx(80000 * 0.20) and x["cost"]["high"] == pytest.approx(80000 * 0.20)
    assert x["market_after"]["score"] >= x["market_before"]["score"]
    assert "Hypothetical" in x["note"] and "assumption" in x["cost"]["note"]
    # a cut can never lower a product's exposure
    for p in x["products_hit"]:
        assert p["score_after"] >= p["score_before"]


def test_what_if_unknown_origin_widens_the_cost_range(isolated):
    csv = "part_number,minerals,annual_spend_usd,origin_country\nA,gallium,1000,China\nB,gallium,3000,\nC,gallium,5000,Japan\n"
    x = C.run(isolated, csv, scenario={"material_id": "gallium", "country": "China", "price_shock_pct": 10})["scenario"]
    assert (x["cost"]["low"], x["cost"]["high"]) == (100.0, 400.0)


def test_scenario_rejects_unknown_material(isolated):
    with pytest.raises(bom.BomError):
        C.run(isolated, CSV, scenario={"material_id": "unobtainium"})


def test_questionnaire_has_blank_answer_columns(isolated):
    res = C.run(isolated, CSV)
    scores, _ = C.score_map(isolated)
    rows = list(__import__("csv").reader(io.StringIO(C.questionnaire_csv(res, scores))))
    assert rows[0] == bom.QUESTIONNAIRE_HEADER and len(rows) == 1 + 6        # 5 mapped rows, one has two minerals
    assert all(r[10] == "" for r in rows[1:])


# ---------------------------------------------------------------- compliance
def test_dfars_flags_covered_origin_and_counts_days():
    rows = bom.parse(CSV)["rows"]
    out = compliance.report(rows, {"defense": True}, today=dt.date(2026, 11, 24))
    d = next(r for r in out if r["id"].startswith("dfars"))
    assert d["applies"] == "yes" and d["counts"]["declared_covered"] >= 1 and d["counts"]["undeclared"] >= 1
    assert d["upcoming"][0]["date"] == "2027-01-01" and d["upcoming"][0]["days"] == 38


def test_rule_dropped_when_user_says_it_does_not_apply():
    rows = bom.parse(CSV)["rows"]
    ids = [r["id"] for r in compliance.report(rows, {"defense": False, "sec_filer": False})]
    assert not any(i.startswith("dfars") or i.startswith("sec") for i in ids)


def test_conflict_minerals_covered_countries_include_rwanda():
    rows = bom.parse(CSV)["rows"]
    sec = next(r for r in compliance.report(rows) if r["id"] == "sec-conflict-minerals")
    assert sec["counts"]["declared_covered"] == 1 and sec["applies"] == "check"


def test_every_rule_has_sources_and_a_review_date():
    for r in compliance.RULES.values():
        assert r["sources"] and all(s["url"].startswith("https://") for s in r["sources"])
        assert set(r["materials"]) <= set(taxonomy.MATERIALS)


# ---------------------------------------------------------------- web + api
def upload(c, data=None, csv=CSV, **fields):
    form = dict(csrf=csrf_of(c), output="screen")
    form.update(fields)
    return c.post("/company/analyze", data=form, files={"file": ("bom.csv", csv.encode(), "text/csv")}, follow_redirects=False)


def test_pages_render(fresh):
    for u in ("/company", "/validation", "/compliance", "/governance", "/alerts", "/embed", "/company/template.csv", "/api/v1/validation", "/api/v1/compliance",
              "/api/v1/governance", "/api/v1/company/template.csv"):
        assert fresh.get(u).status_code == 200, u


def test_upload_requires_csrf(fresh):
    r = fresh.post("/company/analyze", files={"file": ("b.csv", CSV.encode(), "text/csv")})
    assert r.status_code == 403


def test_upload_screen_pdf_and_csv_outputs(fresh):
    r = upload(fresh)
    assert r.status_code == 200 and "Motor 3kW" in r.text and "Simulated" not in r.text
    assert upload(fresh, output="pdf").content[:4] == b"%PDF"
    assert upload(fresh, output="parts_csv").text.startswith("product,part_number")
    q = upload(fresh, output="questionnaire")
    assert q.headers["content-type"].startswith("text/csv") and "origin_country" in q.text


def test_upload_with_what_if_shows_simulation_label(fresh):
    r = upload(fresh, scenario_material="gallium", scenario_country="China", price_shock_pct="25")
    assert r.status_code == 200 and "Simulated" in r.text and "$" in r.text


def test_bad_file_is_a_friendly_422(fresh):
    r = upload(fresh, csv="foo,bar\n1,2\n")
    assert r.status_code == 422 and "part column" in r.text


def test_oversize_body_is_rejected(fresh):
    r = fresh.post("/api/v1/company/analyze", content=b"a" * 3_100_000, headers={"content-type": "text/csv"})
    assert r.status_code == 413


def test_api_analyze_json_and_no_row_leak(client):
    r = client.post("/api/v1/company/analyze?scenario_material=gallium&scenario_country=China&price_shock_pct=10", content=CSV, headers={"content-type": "text/csv"})
    assert r.status_code == 200
    j = r.json()
    assert j["summary"]["mapped_rows"] == 5 and j["scenario"]["parts"]["direct"] == 1 and not any(k.startswith("_") for k in j)
    assert client.post("/api/v1/company/analyze", content="x,y\n1,2", headers={"content-type": "text/csv"}).status_code == 422


def test_company_data_is_never_stored_or_logged(fresh, caplog):
    marker = "ZZ-UNIQUE-PART-7731"
    sup = "Zzyzx Supplier 4412"
    csv = f"product,part_number,supplier,minerals,annual_spend_usd\nSecret Product 9090,{marker},{sup},gallium,424242\n"
    import logging
    with caplog.at_level(logging.DEBUG):
        assert upload(fresh, csv=csv, company_name="Hush Co 5151").status_code == 200
        fresh.post("/api/v1/company/analyze", content=csv, headers={"content-type": "text/csv"})
    from app.db import engine
    dump = []
    with engine.connect() as conn:
        for t in Base.metadata.sorted_tables:
            for row in conn.execute(t.select()):
                dump.append(json.dumps([str(v) for v in row], default=str))
    blob = " ".join(dump) + " " + caplog.text
    for needle in (marker, sup, "Secret Product 9090", "424242", "Hush Co 5151"):
        assert needle not in blob


def test_embed_can_be_framed_but_normal_pages_cannot(fresh):
    e = fresh.get("/embed/materials/gallium")
    assert e.status_code == 200 and "frame-ancestors *" in e.headers["content-security-policy"] and "x-frame-options" not in e.headers
    assert fresh.get("/embed/materials/nope").status_code == 404
    n = fresh.get("/")
    assert n.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in n.headers["content-security-policy"]


# ---------------------------------------------------------------- alerts
PUB = lambda *a, **k: [(2, 1, 6, "", ("52.1.2.3", 443))]
PRIV = lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 443))]


def test_webhook_host_allowlist_and_public_ip(isolated):
    ok = lambda url, body: True
    r = alerts.subscribe(isolated, "slack", "https://hooks.slack.com/services/T/B/x", ["gallium"], post=ok, resolve=PUB)
    assert r["status"] == "active" and len(r["manage_token"]) > 20
    for url, ch, res in [("https://evil.example.com/x", "slack", PUB), ("http://hooks.slack.com/x", "slack", PUB), ("https://hooks.slack.com/x", "slack", PRIV),
                         ("https://hooks.slack.com@evil.com/x", "slack", PUB), ("https://x.webhook.office.com/webhookb2/a", "slack", PUB)]:
        with pytest.raises(alerts.AlertError):
            alerts.subscribe(isolated, ch, url, ["cobalt"], post=ok, resolve=res)
    t = alerts.subscribe(isolated, "teams", "https://prod-12.westus.logic.azure.com:443/workflows/abc", ["cobalt"], post=ok, resolve=PUB)
    assert t["status"] == "active"


def test_webhook_that_rejects_the_test_message_is_not_saved(isolated):
    with pytest.raises(alerts.AlertError):
        alerts.subscribe(isolated, "slack", "https://hooks.slack.com/services/T/B/y", ["gallium"], post=lambda u, b: False, resolve=PUB)
    assert isolated.query(M.AlertSubscription).count() == 0


def test_email_is_off_unless_smtp_is_configured(isolated):
    with pytest.raises(alerts.AlertError):
        alerts.subscribe(isolated, "email", "a@b.com", ["gallium"])


def test_email_confirmation_flow(isolated, monkeypatch):
    monkeypatch.setattr(alerts.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(alerts.settings, "smtp_from", "alerts@example.com")
    sent = []
    r = alerts.subscribe(isolated, "email", "Person@Example.com", ["gallium", "cobalt"], mail=lambda to, s, b: sent.append((to, s, b)) or True)
    assert r["status"] == "pending_email" and sent[0][0] == "person@example.com"
    token = sent[0][2].split("/alerts/confirm/")[1].split()[0]
    changes = [{"material_id": "gallium", "name": "Gallium", "from_score": 60, "to_score": 70, "from_tier": "High", "to_tier": "High", "snapshot_id": 1}]
    assert alerts.dispatch(isolated, changes, mail=lambda *a: True)["sent"] == 0          # not confirmed yet
    assert alerts.confirm(isolated, token) and not alerts.confirm(isolated, token)
    assert alerts.dispatch(isolated, changes, mail=lambda *a: sent.append(a) or True)["sent"] == 1


def test_dispatch_only_for_chosen_materials_and_switches_off_after_failures(isolated):
    alerts.subscribe(isolated, "slack", "https://hooks.slack.com/services/T/B/z", ["gallium"], post=lambda u, b: True, resolve=PUB)
    other = [{"material_id": "zinc", "name": "Zinc", "from_score": 40, "to_score": 50, "from_tier": "Moderate", "to_tier": "Moderate", "snapshot_id": 2}]
    assert alerts.dispatch(isolated, other, post=lambda u, b: True) == {"sent": 0, "failed": 0}
    ga = [{"material_id": "gallium", "name": "Gallium", "from_score": 60, "to_score": 70, "from_tier": "High", "to_tier": "High", "snapshot_id": 3}]
    for _ in range(alerts.MAX_FAILURES):
        assert alerts.dispatch(isolated, ga, post=lambda u, b: False)["failed"] == 1
    assert alerts.dispatch(isolated, ga, post=lambda u, b: True) == {"sent": 0, "failed": 0}
    assert alerts.purge(isolated) == 1 and isolated.query(M.AlertSubscription).count() == 0


def test_manage_link_removes_subscription(isolated):
    r = alerts.subscribe(isolated, "slack", "https://hooks.slack.com/services/T/B/q", ["gallium"], post=lambda u, b: True, resolve=PUB)
    assert alerts.by_manage_token(isolated, r["manage_token"]) and alerts.remove(isolated, r["manage_token"]) and not alerts.remove(isolated, r["manage_token"])


def test_slack_and_teams_payload_shapes():
    assert alerts._payload("slack", "T", "x")["text"].startswith("*T*")
    assert alerts._payload("teams", "T", "x")["attachments"][0]["contentType"] == "application/vnd.microsoft.card.adaptive"


def test_publish_reports_changes_for_alerts(isolated, monkeypatch):
    monkeypatch.setattr(S.settings, "indicative_alerts", True)
    m = taxonomy.MATERIALS["rare-earths"]
    alt = max(m["alternative_sources"], key=lambda a: a["global_share"])["country"]
    isolated.add(M.AlternateSourceReview(material_id="rare-earths", country=alt, status="qualified", evidence_url="https://example.org/e",
                                         evidence_note="Commercial capacity and qualified customers", reviewer="t"))
    isolated.commit()
    r = S.publish_all(isolated)
    assert "rare-earths" in r["created"]
    ch = [c for c in r["changes"] if c["material_id"] == "rare-earths"]
    assert ch and ch[0]["to_score"] < ch[0]["from_score"] and ch[0]["tier_changed"]
    assert S.publish_all(isolated)["changes"] == []          # nothing new, nothing to tell anyone


# ---------------------------------------------------------------- reviews, chain, governance
def test_qualified_alternate_lowers_the_score_and_keeps_the_chain_intact(isolated):
    before = S.latest(isolated, "gallium").composite
    m = taxonomy.MATERIALS["gallium"]
    alt = max(m["alternative_sources"], key=lambda a: a["global_share"])["country"]
    isolated.add(M.AlternateSourceReview(material_id="gallium", country=alt, status="qualified", evidence_url="https://example.org/e",
                                         evidence_note="Commercial capacity and qualified customers", reviewer="t"))
    isolated.commit()
    S.publish_all(isolated)
    after = S.latest(isolated, "gallium")
    assert after.composite < before and after.payload["inputs"]["alternative_sources"]
    assert any(a["qualification_status"] == "qualified" for a in after.payload["inputs"]["alternative_sources"])
    assert S.verify_chain(isolated)["intact"]
    # a later 'unqualified' decision for the same country wins
    isolated.add(M.AlternateSourceReview(material_id="gallium", country=alt, status="unqualified", evidence_url="https://example.org/f",
                                         evidence_note="Capacity not commercial after all", reviewer="t"))
    isolated.commit()
    S.publish_all(isolated)
    assert S.latest(isolated, "gallium").composite == pytest.approx(before) and S.verify_chain(isolated)["intact"]


def test_verification_status_counts(isolated):
    assert S.verification_status(isolated)["import_and_production_checked"] == 0
    for g in ("import", "production"):
        isolated.add(M.DataVerification(material_id="zinc", data_group=g, source_doc="USGS MCS 2026 zinc p.1", outcome="matched", reviewer="t"))
    isolated.commit()
    assert S.verification_status(isolated)["import_and_production_checked"] == 1


def test_signoff_needs_recorded_checks(fresh):
    auth = ("admin", "test-admin-pw")
    page = fresh.get("/admin", auth=auth)
    assert page.status_code == 200
    tok = fresh.cookies.get("mse_csrf")
    r = fresh.post("/admin/signoff/barite", data={"csrf": tok}, auth=auth, follow_redirects=False)
    assert r.status_code == 409 and "import" in r.json()["error"]["message"] if r.headers["content-type"].startswith("application/json") else r.status_code == 409
    for g in ("import", "production"):
        v = fresh.post("/admin/verify/barite", data={"csrf": tok, "data_group": g, "outcome": "matched", "source_doc": "USGS MCS 2026 barite table"}, auth=auth, follow_redirects=False)
        assert v.status_code == 303
    assert fresh.post("/admin/signoff/barite", data={"csrf": tok}, auth=auth, follow_redirects=False).status_code == 303


def test_corrected_check_needs_a_note(fresh):
    auth = ("admin", "test-admin-pw")
    fresh.get("/admin", auth=auth)
    tok = fresh.cookies.get("mse_csrf")
    r = fresh.post("/admin/verify/zinc", data={"csrf": tok, "data_group": "import", "outcome": "corrected", "source_doc": "USGS MCS 2026 zinc"}, auth=auth, follow_redirects=False)
    assert r.status_code == 422


def test_alternate_decision_must_name_a_listed_producer(fresh):
    auth = ("admin", "test-admin-pw")
    fresh.get("/admin", auth=auth)
    tok = fresh.cookies.get("mse_csrf")
    r = fresh.post("/admin/alternate/zinc", data={"csrf": tok, "country": "Atlantis", "status": "qualified", "evidence_url": "https://example.org/x",
                                                  "evidence_note": "A long enough explanation"}, auth=auth, follow_redirects=False)
    assert r.status_code == 422


# ---------------------------------------------------------------- benchmark
def test_benchmark_is_hidden_until_ten_results(isolated):
    for i in range(9):
        assert C.bench_add(isolated, "semiconductors", 50 + i)
    assert C.bench_read(isolated, "semiconductors", 55)["available"] is False
    C.bench_add(isolated, "semiconductors", 70)
    r = C.bench_read(isolated, "semiconductors", 55)
    assert r["available"] and r["n"] == 10 and 0 <= r["percentile"] <= 100
    assert C.bench_add(isolated, "no-such-sector", 5) is False and C.bench_add(isolated, "semiconductors", 500) is False


def test_benchmark_row_holds_nothing_identifying():
    cols = {c.name for c in M.BenchmarkSubmission.__table__.columns}
    assert cols == {"id", "sector", "score", "created_at"}


# ---------------------------------------------------------------- validation
def test_published_validation_matches_the_code():
    stored = json.loads((taxonomy.DATA / "validation_result.json").read_text())
    assert stored == json.loads(json.dumps(validation.run()))


def test_validation_registry_is_sourced_and_inside_platform_scope():
    reg = validation.registry()
    for e in reg["events"]:
        assert e["material_id"] in taxonomy.MATERIALS and e["sources"] and all(s["url"].startswith("https://") for s in e["sources"])
        assert e["announced"] <= e["effective"]


def test_auc_basics():
    import numpy as np
    assert validation.auc(np.array([3, 2, 1, 0.]), np.array([1, 1, 0, 0])) == 1.0
    assert validation.auc(np.array([1, 1, 1, 1.]), np.array([1, 1, 0, 0])) == 0.5


# ---------------------------------------------------------------- data tooling
def _entry_from(source, path, tweak=None, drop=None):
    import csv as _csv
    sys_path = __import__("sys").path
    import importlib.util
    spec = importlib.util.spec_from_file_location("vt", str(taxonomy.DATA.parent / "scripts" / "verify_transcription.py"))
    vt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vt)
    want = vt.load(source)
    with open(path, "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["material", "group", "country", "value"])
        for (m, g, c), v in want.items():
            if drop and (m, g, c) == drop:
                continue
            w.writerow([m, g, c, v + (1 if tweak == (m, g, c) else 0)])
    return vt


def test_double_entry_check_accepts_a_faithful_copy_and_flags_differences(tmp_path):
    src = str(taxonomy.DATA / "source_mcs2024.json")
    vt = _entry_from(src, tmp_path / "ok.csv")
    got, problems = vt.read_entry(tmp_path / "ok.csv")
    r = vt.compare(vt.load(src), got)
    assert not problems and not r["mismatched"] and not r["missing_in_entry"] and r["matched"] == r["total"] > 200
    vt = _entry_from(src, tmp_path / "bad.csv", tweak=("gallium", "import", "China"), drop=("zinc", "nir", ""))
    got, _ = vt.read_entry(tmp_path / "bad.csv")
    r = vt.compare(vt.load(src), got)
    assert [k for k, a, b in r["mismatched"]] == [("gallium", "import", "China")] and r["missing_in_entry"] == [("zinc", "nir", "")]
    assert vt.main(["x", src, str(tmp_path / "bad.csv")]) == 1 and vt.main(["x", src, str(tmp_path / "ok.csv")]) == 0


def test_taxonomy_rebuilds_identically_from_the_source_file(tmp_path):
    import subprocess, sys
    root = taxonomy.DATA.parent
    out = tmp_path / "mc.json"
    r = subprocess.run([sys.executable, "-I", str(root / "scripts" / "build_taxonomy.py"), "--out", str(out)], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(out.read_text()) == json.loads((taxonomy.DATA / "material_categories.json").read_text())
