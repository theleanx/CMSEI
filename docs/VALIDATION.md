# Validation

Published result: https://cmsei-web.onrender.com/validation, data in `data/validation_result.json`, labels and sources in `data/shocks.json`. Re-run with `python3 -I scripts/backtest_shocks.py`; a test fails if the stored result is stale.

## Question
Did the index rank higher the materials that faced a government export restriction between 2020 and 2025?

## Labels
Six of the 19 materials: gallium (China, 2023), cobalt (DR Congo, 2025), rare earths (China, 2025), bismuth and indium (China, 2025), nickel (Indonesia ore ban, 2020). Each has an official or law-firm source in the registry. Germanium, tungsten, tellurium and molybdenum had restrictions too but are not among the 19 scored materials. A 2022 cobalt restriction was looked for and not found, so it is not used.

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
