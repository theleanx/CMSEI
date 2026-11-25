# Refreshing the data

**Why now.** The import tables are 2019 to 2022. The platform's own staleness rule (spec 4.8) drops a grade one step once data is more than 48 months old. From **January 2027** that applies to every material's import figures, so every score becomes Indicative (grade C) and alerts stay off. USGS published Mineral Commodity Summaries 2026 in February 2026 (DOI 10.3133/mcs2026, data release 10.5066/P1WKQ63T).

**Why this is manual.** The build environment used so far cannot reach USGS, Census or Comtrade. Earlier figures were read through a page reader and not checked digit by digit, and repeating that would repeat the problem. The safe path is a person copying from the published tables plus a second person checking.

## Steps
1. Download the MCS 2026 chapters (or the data release CSVs) for the 19 materials.
2. Copy `data/source_mcs2024.json` to `data/source_mcs2026.json` and update the figures: US import shares by country (the chapter's "Import Sources" line), world production by country (the "World Production" table), and net import reliance. Add an edition block at the top level:
   ```json
   "edition": {"mcs_edition": 2026, "production_year": 2025, "import_period": "2021-24", "import_year": 2024}
   ```
   Check the years against the chapters: production years can differ by material, and some chapters mark figures withheld. Do not fill a gap with a guess.
3. Update `source` and `transcription_note` in the file to say who copied it and when.
4. Rebuild: `python3 -I scripts/build_taxonomy.py --source data/source_mcs2026.json`. Review the diff of `data/material_categories.json`.
5. Second person: double-entry check with `scripts/verify_transcription.py` (see GOVERNANCE.md).
6. Run `pytest`. The paper-alignment tests pin the 2024 worked example, so expect them to fail until the 2024 figures are held in a fixture. Move the 2024 file's expectations into test fixtures rather than deleting them.
7. Refresh processing-stage figures (IEA) for cobalt and rare earths, which are separate sources in `scripts/build_taxonomy.py`.
8. Record the checks in the admin console, then deploy.

## What is not automated, and why
Census (US import values by country and HS code) and Comtrade (world trade) can cross-check import shares, but each needs an HS-code mapping per material that a person must make; the taxonomy leaves `trade_codes` empty on purpose. Adding automated pulls without that mapping would produce plausible but unreliable shares.
