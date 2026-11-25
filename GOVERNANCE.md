# Governance

## Who decides what
- **Maintainer** (see MAINTAINERS.md): publishes data editions, signs off materials, decides corrections, approves held events, and records alternate-source decisions.
- **Second reviewer** (Priyanshi Joshi, co-author): performs the double-entry check below so the person who typed a figure is not the only one who checked it.

## What "reviewed" means
A material shows **reviewed** only when its import and production figures have a recorded comparison with the published table, entered in the admin console under a named reviewer, document and page. The admin console refuses sign-off otherwise.

## Data check (double entry)
1. Person A prepares the data file from the published USGS tables.
2. Person B, without looking at the data file, types the same figures from the PDF or the USGS data release into a CSV (`material,group,country,value`).
3. Run `python3 -I scripts/verify_transcription.py <data file> <entry.csv>`. Resolve every difference against the published table.
4. Person B records the check per material and group in the admin console ("Data checks"), naming the document and page.
5. Only then sign off the material.

## Alternate sources
An alternate producer earns credit in the score only after a person records a **qualified** decision with an evidence link and a reason (commercial capacity, customer qualification, no restriction that blocks US supply). The newest decision per country wins, every decision is kept, and the score is republished into the append-only snapshot log. Nothing is credited by default.

## Changing the data or formula
- Data edition: new `data/source_mcs20XX.json` (with an `edition` block), rebuild with `scripts/build_taxonomy.py --source ...`, run the double-entry check, then deploy. See docs/DATA-REFRESH.md.
- Formula or tables: bump `FORMULA_VERSION` and the table versions. Old snapshots keep regenerating under their own version.
- Compliance rules: edit `data/compliance_rules.json`, update `last_reviewed`, add the source. Have counsel review before relying on them.
- Validation registry: add sourced events to `data/shocks.json` and run `scripts/backtest_shocks.py`. Add events whether or not they help the index.

## What this project does not do
It does not describe any company, give sourcing, legal or investment advice, or certify compliance. See the Terms page.
