"""The platform must reproduce the paper's published numbers and follow its stated rules."""
import pytest
from app.engine import scoring as sc, simulator, uncertainty, taxonomy

WORKED = {"import_shares": [90, 6, 4], "raw_hhi": 4000, "proc_hhi": 8200, "d": 1.3,
          "alternative_sources": [
              {"country": "Australia", "global_share": 6, "qualification_status": "qualified", "included_in_n_alt": True},
              {"country": "Vietnam-like", "global_share": 3, "qualification_status": "unverified", "included_in_n_alt": True}]}


def test_worked_example_and_scenario_table():
    r = sc.score_inputs(WORKED, ["proposed"])
    assert (round(r["C"], 2), round(r["P"], 1), r["S"], r["G"]) == (81.52, 69.4, 65.0, 1.08)
    assert r["composite"] == pytest.approx(77.45, abs=0.01) and r["tier"] == "High"
    want = {("add_source", None): -7, ("event_change", "none"): -5, ("easier_substitution", None): -4,
            ("supply_cut", "partial"): 5, ("supply_cut", "full"): 16}
    for (fam, opt), d in want.items():
        assert simulator.simulate(WORKED, ["proposed"], fam, opt)["delta_rounded"] == d


def test_uncertainty_matches_paper_section_V_A():
    u = uncertainty.run("worked-example", WORKED, ["proposed"])
    assert u["range_low"] == pytest.approx(71.7, abs=0.3) and u["range_high"] == pytest.approx(83.7, abs=0.3)
    assert u["tier_shares"]["High"] == pytest.approx(0.746, abs=0.01) and u["tier_shares"]["Critical"] == pytest.approx(0.254, abs=0.01)
    assert u["weights_only_same_tier"] == pytest.approx(0.992, abs=0.005)


def test_only_verified_sources_earn_credit():
    a = lambda st: [{"country": "X", "global_share": 10, "qualification_status": st, "included_in_n_alt": True}]
    assert sc.n_eff(a("qualified")) == 1.0
    for st in ("provisional", "unverified", "unqualified"):
        assert sc.n_eff(a(st)) == 0.0


def test_official_scores_give_no_credit_and_provisional_is_a_sensitivity():
    m = taxonomy.MATERIALS["rare-earths"]
    inp = sc.inputs_from_material(m)
    official = sc.score_inputs(inp)
    assert official["N_eff"] == 0.0 and round(official["composite"], 1) == 74.7 and official["tier"] == "High"
    u = uncertainty.run("rare-earths", inp, [])
    assert u["provisional_credit_composite"] == pytest.approx(50.9, abs=0.1) and u["provisional_credit_tier"] == "Moderate"
    assert u["tier_depends_on_alternates"] is True


def test_result_page_states_the_credit_rule(client):
    from tests.conftest import csrf_of
    t = client.get("/materials/rare-earths").text
    assert "No other producing country has been verified" in t and "Treat that as a sensitivity" in t


def test_sectors_leave_out_grade_c_by_default(client):
    j = client.get("/api/v1/sectors").json()["sectors"]
    assert all(s["status"] == "not_scored" for s in j)
    assert all("leaves out of sector means" in s["reason"] for s in j)
    prev = [s for s in j if s["indicative_view"]]
    assert prev and all("Not a sector score" in s["indicative_view"]["label"] for s in prev)
    page = client.get("/sectors").text
    assert "Indicative preview" in page and "Not scored" in page


def test_sectors_score_when_all_members_are_reviewed(db_session=None):
    from app.db import SessionLocal
    from app.services import snapshots as S
    from app.config import settings
    settings.indicative_in_sectors = True
    try:
        with SessionLocal() as db:
            rows = S.sector_scores(db)
            assert any(r["status"] == "scored" for r in rows)
    finally:
        settings.indicative_in_sectors = False
        with SessionLocal() as db:
            S.sector_scores(db)
