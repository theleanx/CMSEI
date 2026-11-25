# Validation

Published result: https://cmsei-web.onrender.com/validation, data in `data/validation_result.json`, labels and sources in `data/shocks.json`. Re-run with `python3 -I scripts/backtest_shocks.py`; a test fails if the stored result is stale.

## Question
Did the index rank higher the materials that faced a government export restriction between 2020 and 2025?

## Labels
Six of the 19 materials: gallium (China, 2023), cobalt (DR Congo, 2025), rare earths (China, 2025), bismuth and indium (China, 2025), nickel (Indonesia ore ban, 2020). Each has an official or law-firm source in the registry. Germanium, tungsten and tellurium had sourced restrictions too (registry shocks-2) but are not scored yet, so they are listed as unscored positives and join the tests automatically once added (docs/ADD-MATERIAL.md). Molybdenum is not on the coverage list yet. A 2022 cobalt restriction was looked for and not found, so it is not used.

## Result (as run 2026-11-24)
| Measure | AUC | 95% interval |
|---|---|---|
| CMSEI composite | 0.744 | 0.487 to 0.949 |
| Top producer's world share | 0.846 | 0.641 to 1.0 |
| World-production HHI | 0.821 | 0.603 to 1.0 |
| US import HHI | 0.519 | 0.192 to 0.821 |

Difference, CMSEI minus top-producer share: -0.102 (interval -0.282 to 0.051). Dropping the nickel label, or keeping only China-imposed restrictions, raises every AUC but leaves the order the same.

## Reading
The index ranks restricted materials above the rest more often than chance, but the interval reaches chance, and a one-line concentration measure does at least as well. This agrees with the earlier backtests on the Methodology page. It is a screening view, not a forecast.

## Limits
Six positives. The registry is not an exhaustive search, so some negatives may be mislabelled. The data are unverified 2019-23 tables. The labels were built after the index design. The test says nothing about timing or size of disruptions.

## The frozen forecast (the test that cannot be gamed)
Everything above was checked after the events, with labels built after the index design. To get a fair test, `scripts/freeze_forecast.py` wrote `data/prospective_forecast.json` on 2026-11-25: the scores, the two baselines, the question, the two hypotheses, the decision rule and a fingerprint. The window is 2026-12-01 to 2027-11-30. Only restrictions announced in that window, recorded with an official or law-firm source in `data/shocks.json`, count as positives. The file must not be changed; a later freeze gets a new version and the old file stays in git history.

Decision rule, fixed in advance: if CMSEI's AUC is below the top-producer-share AUC with at least 3 positives, the front page says the index does not beat simple concentration.

Larger label set: `data/shocks_candidates.json` lists reported restrictions (graphite 2023, antimony 2024, and others) that still need an official or law-firm source. The OECD Inventory of Export Restrictions on Industrial Raw Materials should be searched by someone with access and each event recorded with its source. Nothing in the candidates file is counted.
