# Scoring substitution difficulty (D)

D says how hard it is to replace the material itself in a typical application. Range 0.5 to 1.5. Today every material is 1.0 and marked "estimated". The score changes: S = min(100, 100 / (1 + alternates) × D).

## Anchors
| D | Meaning | Example of what it looks like |
|---|---|---|
| 0.5 | A drop-in substitute exists and qualification takes under 6 months | Use another solder alloy |
| 0.75 | Substitute exists, some redesign or re-qualification, under 2 years | |
| 1.0 | Substitute possible with a clear performance or cost penalty, 2 to 4 years | |
| 1.25 | Substitutes lose key performance, long re-qualification (regulated or safety-critical) | |
| 1.5 | No acceptable substitute in the typical application | |

Rate the material in its largest or most typical US industrial use, not the best case.

## Who rates
At least **5** experts per material (supplier quality, materials engineering, procurement for that material). Independent ratings: no one sees another's number. Reviewers are not paid per answer.

## Steps
1. `python3 -I scripts/aggregate_d.py --template sheet.csv` (a ready sheet is in `docs/templates/expert_d_sheet.csv`).
2. Each expert fills `expert_id` (any code), `d`, and a one-sentence `rationale` naming the application.
3. Join the sheets and run `python3 -I scripts/aggregate_d.py --in ratings.csv`. Materials with fewer than 5 experts stay at 1.0. The result is the median; if the highest and lowest differ by more than 0.5 the page says the experts disagreed.
4. `python3 -I scripts/build_taxonomy.py`, then `python3 -I scripts/backtest_shocks.py`, then `python3 -m pytest -q`, then commit. Expert ids are not written to the output.

The back-test is re-run with the new D. Do not pick the D values by how they move the back-test.
