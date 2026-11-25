# Adding a material (two people, no guessing)

Why: germanium, graphite, antimony, tungsten and tellurium are not scored (see `data/coverage.json`, page `/coverage`). Their numbers are not typed from memory. Two people type them from the USGS tables, and a script refuses to continue unless the two copies match.

Who: Person A and Person B (for example Ankit and Priyanshi Joshi). Do not look at each other's file.

1. Open the material's page in the USGS Mineral Commodity Summaries (the link is on `/coverage`). Use the same edition as the rest of the data (see `data/source_mcs2024.json`).
2. Each person makes a CSV with columns `material,group,country,value`:
   - `import`: one row per country in "Import Sources", value = the percent printed.
   - `production`: one row per country in the world production table, value = the latest-year quantity as printed. Include `Other` if printed.
   - `nir`: one row, country blank, value = net import reliance percent.
   Use the same country spellings as the source file (`DRC`, `SouthAfrica`, `Korea`, `PNG`...).
3. Compare and write (nothing is written if any figure differs):
   ```
   python3 -I scripts/merge_entry.py --source data/source_mcs2024.json --a entry_A.csv --b entry_B.csv \
     --material germanium --form metal --document "USGS MCS 2024, Germanium, pp. X-Y" --entered-by "Name A,Name B"
   ```
4. Rebuild and re-run the back-test (it picks up the new label automatically):
   ```
   python3 -I scripts/build_taxonomy.py
   python3 -I scripts/backtest_shocks.py
   python3 -m pytest -q
   ```
   If the builder lists countries missing from `REGION_OF`, add them in `scripts/build_taxonomy.py`.
5. In the admin console record the data check for the material, then sign off. The site shows the material as "double entry" until then.
6. Add the material's alternates only after a person reviews them (admin: alternate decision). Until then none earns credit.

What this does not do: it does not check that the right table was used. The `--document` note records which pages both people read.
Also needed per material: a processing-stage entry in `data/processing_stage.json` if a sourced share exists (without one the score is marked Indicative), and, for tungsten, a counsel check of whether defense sourcing rules (DFARS) cover it before it is added to `data/compliance_rules.json`.
