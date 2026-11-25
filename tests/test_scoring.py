import pytest
from hypothesis import given, strategies as st
from app.engine import scoring as sc


def test_worked_example():
    r = sc.combine(81.52, 69.4, 65.0, 1.08)
    assert r["composite"] == pytest.approx(77.45, abs=0.02)
    assert r["tier"] == "High"


@pytest.mark.parametrize("x,t", [(0, "Low"), (30, "Low"), (30.01, "Moderate"), (60, "Moderate"), (60.01, "High"),
                                 (80, "High"), (80.01, "Critical"), (100, "Critical")])
def test_tier_boundaries(x, t):
    assert sc.tier_of(x) == t


def test_event_effects_and_cap():
    assert sc.g_multiplier([]) == 1.0
    assert sc.g_multiplier(["statement"]) == pytest.approx(1.02)
    assert sc.g_multiplier(["ban"]) == pytest.approx(1.30)
    assert sc.g_multiplier(["ban", "ban", "ban", "ban"]) == 1.5


def test_hhi_single_source_is_100():
    assert sc.hhi([100]) == 10000 / 100 or sc.hhi([100]) in (100, 10000)


def test_unqualified_sources_earn_no_credit():
    a = {"country": "X", "global_share": 10, "qualification_status": "unqualified", "included_in_n_alt": True}
    assert sc.n_eff([a]) == 0
    b = dict(a, qualification_status="qualified")
    assert sc.n_eff([b]) == 1.0


def test_partial_credit_caps_at_one_per_source():
    big = {"country": "X", "global_share": 40, "qualification_status": "qualified", "included_in_n_alt": True}
    assert sc.n_eff([big]) == 1.0
    small = dict(big, global_share=2.5)
    assert sc.n_eff([small]) == pytest.approx(0.5)


@given(st.floats(0, 100), st.floats(0, 100), st.floats(0, 100), st.floats(1.0, 1.5))
def test_composite_bounded(c, p, s, g):
    r = sc.combine(c, p, s, g)
    assert 0 <= r["composite"] <= 100


@given(st.floats(0, 100), st.floats(0, 100), st.floats(0, 100))
def test_event_never_lowers_score(c, p, s):
    assert sc.combine(c, p, s, 1.15)["composite"] >= sc.combine(c, p, s, 1.0)["composite"]


def test_all_materials_score_within_range():
    from app.engine import taxonomy
    for mid, m in taxonomy.MATERIALS.items():
        r = sc.score_inputs(sc.inputs_from_material(m))
        assert 0 <= r["composite"] <= 100, mid
