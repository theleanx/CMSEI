"""Researcher fixes: coverage gap, two-person entry, expert D, frozen forecast, baseline, second reviewer."""
import csv
import hashlib
import json
import subprocess
import sys
import numpy as np
import pytest
from app.engine import bom, coverage, taxonomy, validation
from app.config import settings

ROOT = taxonomy.DATA.parent
PY = [sys.executable, "-I"]


def run(*args, **kw):
    return subprocess.run(PY + [str(ROOT / args[0])] + list(args[1:]), cwd=ROOT, capture_output=True, text=True, **kw)


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["material", "group", "country", "value"])
        w.writerows(rows)


# ------------------------------------------------------------ coverage
def test_gap_list_names_the_five_and_none_are_invented_scores():
    ids = {m["id"] for m in coverage.GAPS}
    assert ids == {"germanium", "graphite", "antimony", "tungsten", "tellurium"}
    assert not ids & set(taxonomy.MATERIALS)
    assert coverage.public()["scored"] == 19


def test_bom_flags_unscored_minerals_without_scoring_them():
    p = bom.parse("product,part_number,description,minerals\nLens,L1,Germanium infrared optics,\nDrill,D1,Tungsten carbide insert,tungsten\nMotor,M1,magnet,rare-earths\n")
    by = {r["part"]: r for r in p["rows"]}
    assert by["L1"]["unscored"] == ["germanium"] and by["L1"]["minerals"] == []
    assert by["D1"]["unscored"] == ["tungsten"] and by["M1"]["unscored"] == []


def test_company_screen_says_not_scored(client):
    r = client.get("/coverage")
    assert r.status_code == 200 and "Germanium" in r.text and "docs/ADD-MATERIAL.md" in r.text
    j = client.get("/api/v1/coverage").json()
    assert [m["id"] for m in j["not_scored"]][0] == "germanium"
    page = client.get("/company")
    assert page.status_code == 200


# ------------------------------------------------------------ two-person entry
def _entry(tmp, name, rows):
    p = tmp / name
    write_csv(p, rows)
    return str(p)


GOOD = [("germanium", "import", "China", 40), ("germanium", "import", "Belgium", 20), ("germanium", "production", "China", 90),
        ("germanium", "production", "Russia", 5), ("germanium", "nir", "", 50)]


def _source(tmp):
    src = tmp / "src.json"
    d = json.loads((taxonomy.DATA / "source_mcs2024.json").read_text())
    src.write_text(json.dumps(d))
    return src


def test_merge_refuses_when_the_two_copies_differ(tmp_path):
    src = _source(tmp_path)
    before = src.read_text()
    bad = [r if r[3] != 20 else (*r[:3], 21) for r in GOOD]
    r = run("scripts/merge_entry.py", "--source", str(src), "--a", _entry(tmp_path, "a.csv", GOOD), "--b", _entry(tmp_path, "b.csv", bad),
            "--material", "germanium", "--form", "metal", "--document", "test", "--entered-by", "A,B")
    assert r.returncode == 1 and "disagree" in r.stdout and src.read_text() == before


def test_merge_needs_two_different_people(tmp_path):
    src = _source(tmp_path)
    r = run("scripts/merge_entry.py", "--source", str(src), "--a", _entry(tmp_path, "a.csv", GOOD), "--b", _entry(tmp_path, "b.csv", GOOD),
            "--material", "germanium", "--form", "metal", "--document", "test", "--entered-by", "A,A")
    assert r.returncode == 1 and "germanium" not in json.loads(src.read_text())["import"]


def test_merged_material_builds_and_scores_and_is_marked_double_entry(tmp_path):
    src = _source(tmp_path)
    r = run("scripts/merge_entry.py", "--source", str(src), "--a", _entry(tmp_path, "a.csv", GOOD), "--b", _entry(tmp_path, "b.csv", GOOD),
            "--material", "germanium", "--form", "metal", "--document", "TEST DATA ONLY", "--entered-by", "A,B")
    assert r.returncode == 0, r.stdout + r.stderr
    out = tmp_path / "mc.json"
    rcm_before = (taxonomy.DATA / "region_country_map.json").read_text()
    b = run("scripts/build_taxonomy.py", "--source", str(src), "--out", str(out))
    assert b.returncode == 0, b.stderr
    mats = {m["id"]: m for m in json.loads(out.read_text())["materials"]}
    assert len(mats) == 20 and mats["germanium"]["transcription"] == "double_entry"
    assert mats["germanium"]["dominant_country"] == "China" and mats["gallium"]["transcription"] == "unverified"
    assert mats["germanium"]["substitution_difficulty"] == 1.0 and mats["germanium"]["d_status"] == "estimated"
    # the build rewrites the region map; with countries already known it must come out unchanged
    assert (taxonomy.DATA / "region_country_map.json").read_text() == rcm_before
    # the double-entry compare tool still reads the extended source file
    import sys as _s
    _s.path.insert(0, str(ROOT / "scripts"))
    import verify_transcription as vt
    assert ("germanium", "nir", "") in vt.load(str(src))


# ------------------------------------------------------------ expert D
def _ratings(tmp, rows):
    p = tmp / "r.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["expert_id", "material", "d", "rationale"])
        w.writerows(rows)
    return str(p)


def test_d_needs_five_experts_uses_median_and_flags_disagreement(tmp_path):
    rows = [(f"e{i}", "gallium", v, "GaN power chips") for i, v in enumerate([1.1, 1.2, 1.3, 1.2, 1.25])]
    rows += [(f"e{i}", "zinc", v, "galvanizing") for i, v in enumerate([0.5, 0.6, 1.4, 1.0, 0.7])]
    rows += [(f"e{i}", "tin", 1.0, "solder") for i in range(4)]
    out = tmp_path / "d.json"
    r = run("scripts/aggregate_d.py", "--in", _ratings(tmp_path, rows), "--out", str(out))
    assert r.returncode == 0 and "tin" in r.stdout
    d = json.loads(out.read_text())["materials"]
    assert d["gallium"]["d"] == 1.2 and not d["gallium"]["disagreement"] and d["gallium"]["n_experts"] == 5
    assert d["zinc"]["d"] == 0.7 and d["zinc"]["disagreement"] and "tin" not in d
    assert "e0" not in out.read_text()


@pytest.mark.parametrize("row", [("e1", "gallium", 1.8, "x"), ("e1", "gallium", 1.0, ""), ("", "gallium", 1.0, "x")])
def test_d_rejects_bad_rows(tmp_path, row):
    r = run("scripts/aggregate_d.py", "--in", _ratings(tmp_path, [row]), "--out", str(tmp_path / "d.json"))
    assert r.returncode == 1 and not (tmp_path / "d.json").exists()


def test_builder_applies_expert_d_and_scores_move(tmp_path):
    ed = tmp_path / "ed.json"
    ed.write_text(json.dumps({"materials": {"gallium": {"d": 1.4, "n_experts": 6, "min": 1.2, "max": 1.5, "disagreement": False, "reviewed": "2026-12-01"}}}))
    out = tmp_path / "mc.json"
    assert run("scripts/build_taxonomy.py", "--expert-d", str(ed), "--out", str(out)).returncode == 0
    g = {m["id"]: m for m in json.loads(out.read_text())["materials"]}["gallium"]
    assert g["substitution_difficulty"] == 1.4 and g["d_status"] == "expert_reviewed" and g["d_review"]["n_experts"] == 6


def test_processing_entries_need_a_source(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps({"entries": {"cobalt": {"country": "China", "share": 75.0, "basis": "b", "grade": "B", "data_year": 2022, "url": "u"}}}))
    r = run("scripts/build_taxonomy.py", "--processing", str(p), "--out", str(tmp_path / "x.json"))
    assert r.returncode != 0 and "source" in r.stderr


def test_full_processing_distribution_gives_a_real_hhi(tmp_path):
    p = tmp_path / "p.json"
    base = {"country": "China", "share": 60.0, "basis": "b", "source": "s", "grade": "B", "data_year": 2024, "url": "u"}
    p.write_text(json.dumps({"entries": {"cobalt": {**base, "shares": {"China": 60.0, "Finland": 20.0, "Japan": 10.0}}}}))
    out = tmp_path / "x.json"
    assert run("scripts/build_taxonomy.py", "--processing", str(p), "--out", str(out)).returncode == 0
    c = {m["id"]: m for m in json.loads(out.read_text())["materials"]}["cobalt"]
    assert c["processing_hhi_baseline"] == 60 ** 2 + 20 ** 2 + 10 ** 2


# ------------------------------------------------------------ frozen forecast and validation
def test_forecast_file_is_intact_and_frozen_before_its_window():
    fc = json.loads((taxonomy.DATA / validation.FORECAST).read_text())
    assert fc["content_sha256"] == validation.forecast_hash(fc)
    assert fc["frozen_on"] < fc["window"]["start"] and len(fc["ranking"]) == 19
    assert fc["plan"]["decision_rule"] and fc["plan"]["not_allowed"]


def test_forecast_matches_current_scores_while_the_data_are_unchanged():
    fc = json.loads((taxonomy.DATA / validation.FORECAST).read_text())
    if hashlib.sha256((taxonomy.DATA / "material_categories.json").read_bytes()).hexdigest() != fc["taxonomy_sha256"]:
        pytest.skip("taxonomy changed after the freeze; the forecast keeps its own frozen values")
    feats = validation.features()
    assert {r["id"]: r["cmsei"] for r in fc["ranking"]} == {k: round(v["cmsei"], 3) for k, v in feats.items()}


def test_freezing_again_is_refused():
    assert run("scripts/freeze_forecast.py", "--version", "fc-2", "--start", "2027-01-01", "--end", "2027-12-31").returncode == 1


def test_prospective_waits_then_scores(monkeypatch):
    reg = validation.registry()
    assert validation.prospective(reg)["status"] == "waiting"
    fc = json.loads((taxonomy.DATA / validation.FORECAST).read_text())
    top, low = fc["ranking"][0]["id"], fc["ranking"][-1]["id"]
    ev = {"id": "x", "material_id": top, "country": "China", "announced": "2027-03-01"}
    out = validation.prospective({**reg, "events": reg["events"] + [ev]})
    assert out["status"] == "scored" and out["positives"] == [top] and out["auc"]["cmsei"] == 1.0
    old = {**ev, "announced": "2026-01-01"}   # before the window: never counts
    assert validation.prospective({**reg, "events": [old]})["status"] == "waiting"
    new_mat = {**ev, "material_id": "germanium"}  # outside the frozen set: listed, not scored
    o = validation.prospective({**reg, "events": [new_mat]})
    assert o["status"] == "waiting" and o["events_outside_frozen_set"] == ["germanium"]


def test_unscored_restrictions_are_listed_not_counted():
    res = validation.run()
    assert res["positives_not_scored"] == ["germanium", "tellurium", "tungsten"]
    assert res["n_positive"] == 6 and res["n_materials"] == 19
    reg = validation.registry()
    assert {e["material_id"] for e in reg["events"]} >= {"germanium", "tungsten", "tellurium"}
    assert all(e["sources"] for e in reg["events"])


def test_candidate_events_are_never_labels():
    cand = json.loads((taxonomy.DATA / "shocks_candidates.json").read_text())
    assert cand["candidates"] and "Nothing here is counted" in cand["note"]
    assert "graphite" not in {e["material_id"] for e in validation.registry()["events"]}


def test_validation_page_shows_forecast_and_unscored(client):
    t = client.get("/validation").text
    assert "frozen forecast" in t and "Restricted but not scored" in t and "Germanium" in t


# ------------------------------------------------------------ baseline and reviewer
def test_material_page_and_api_show_the_simple_baseline(client):
    t = client.get("/materials/gallium").text
    assert "The simple check, side by side" in t and "estimated, not expert-reviewed" in t
    j = client.get("/api/v1/materials/gallium").json()
    b = j["inputs"]["baseline"]
    m = taxonomy.MATERIALS["gallium"]
    assert b["top_producer"] == "China" and b["production_hhi"] == m["production"]["hhi"]


def test_second_reviewer_is_named_on_site_and_api(client):
    assert settings.reviewer_name == "Priyanshi Joshi"
    g = client.get("/governance").text
    assert "Priyanshi Joshi" in g and "shared login" in g
    assert client.get("/api/v1/data-status").json()["second_reviewer"]["name"] == "Priyanshi Joshi"
    assert "Priyanshi Joshi" in open(ROOT / "MAINTAINERS.md").read()


def test_upload_with_unscored_part_warns_on_screen_and_still_makes_pdf(fresh):
    from tests.test_company import upload
    csv_text = "product,part_number,description,supplier,minerals,annual_spend_usd\nLens,L1,Germanium infrared optics,Optix,,9000\nMotor,M1,magnet,Acme,rare-earths,1000\n"
    r = upload(fresh, csv=csv_text)
    assert r.status_code == 200 and "Not scored" in r.text and "germanium" in r.text.lower() and "/coverage" in r.text
    assert upload(fresh, csv=csv_text, output="pdf").content[:4] == b"%PDF"
