"""Scenario simulator (spec 4.6). Hypothetical market changes only. Uses the section 4.2 formula and nothing else.

Four families:
  add_source        a new qualified source is added: N_eff + 1
  event_change      the active event stage on the dominant country is replaced (none, statement, proposed, enacted, ban)
  easier_substitution  D drops one step (0.3), floor 0.5
  supply_cut        partial cut = enacted licensing stage, full cut-off = effective ban (modeling choice, unvalidated)
A scenario event REPLACES earlier stages of the same situation. It never stacks.
"""
from __future__ import annotations
from . import scoring as sc

D_STEP = 0.3
FAMILIES = {
    "add_source": "A new qualified source is added",
    "event_change": "Geopolitical conditions change",
    "easier_substitution": "Substitution gets easier",
    "supply_cut": "Dominant country's supply is cut",
}
EVENT_OPTIONS = ("none", "statement", "proposed", "enacted", "ban")
CUT_OPTIONS = {"partial": "enacted", "full": "ban"}


def simulate(inp: dict, active_stages: list, family: str, option: str | None = None) -> dict:
    """Returns official and simulated results. `active_stages` are the stages of currently active events
    (one entry per situation). The dominant-country situation is the one replaced by event scenarios;
    to keep it simple and conservative all active stages are treated as that situation, as the spec
    example does (one active event)."""
    base = sc.score_inputs(inp, active_stages)
    inp2, stages2 = dict(inp), list(active_stages)
    if family == "add_source":
        n_plus = sc.n_eff(inp["alternative_sources"]) + 1.0
        c = base["C"]; p = base["P"]
        s = sc.s_score(n_plus, inp["d"])
        sim = sc.combine(c, p, s, base["G"]); sim["N_eff"] = n_plus
    else:
        if family == "event_change":
            if option not in EVENT_OPTIONS:
                raise ValueError("bad option")
            stages2 = [] if option == "none" else [option]
        elif family == "supply_cut":
            if option not in CUT_OPTIONS:
                raise ValueError("bad option")
            stages2 = [CUT_OPTIONS[option]]
        elif family == "easier_substitution":
            inp2["d"] = max(0.5, round(inp["d"] - D_STEP, 2))
        else:
            raise ValueError("unknown family")
        sim = sc.score_inputs(inp2, stages2)
    return {
        "family": family, "option": option, "label": FAMILIES[family],
        "official": {"composite": base["composite"], "tier": base["tier"], "G": base["G"], "S": base["S"]},
        "simulated": {"composite": sim["composite"], "tier": sim["tier"], "G": sim["G"], "S": sim["S"], "N_eff": sim.get("N_eff")},
        "delta": sim["composite"] - base["composite"],
        "delta_rounded": sc.round_score(sim["composite"]) - sc.round_score(base["composite"]),
        "simulated_label": "Simulated",
        "note": "Hypothetical. Never replaces the official score. The mapping from supply cut to event stage is a modeling choice and is unvalidated.",
    }
