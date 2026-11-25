# Getting a parts list out of SAP

No live SAP connector exists yet. The Your-parts page reads a CSV, and it recognizes SAP-style headers, so an export from SAP works without renaming columns.

## Columns it recognizes
| In your file | Used as |
|---|---|
| `MATNR` / `IDNRK` / `part_number` | part |
| `MAKTX` / `description` | description (matched to materials by name) |
| `LIFNR` / `NAME1` / `supplier` | supplier |
| `HERKL` / `origin_country` | declared origin of the part (country of origin) |
| `minerals` | list of tracked materials the part depends on, separated by `;` (most reliable) |
| `annual_spend_usd` | spend, for share-of-spend figures and what-if cost |
| header material (`product`) | the product the part belongs to |

`LAND1` is deliberately **not** read as origin: in vendor master it is the vendor's country, not where the material was mined or processed.

## One way to build the file
- BOM explosion for each finished good (transaction CS12, or the standard BOM report download) gives product and component (`IDNRK`).
- Component descriptions from the material master text (`MAKT-MAKTX`).
- Vendor from the purchasing info record or source list (`EINA`/`EORD`, name from `LFA1`).
- Origin from the material master plant data (`MARC-HERKL`) where your company maintains it. Many do not, which is why the platform treats blank origin as unknown, not as safe.
- Spend from your own purchasing analytics, summed per component and vendor over 12 months.

A Basis or reporting colleague can join these in a Quick View or a CDS view and download CSV. Table and field names above are standard but vary by release and customization. They have not been tested against a live system here.

## Mapping parts to minerals
SAP does not know which parts contain which critical minerals. Either add a `minerals` column from your engineering or compliance data (product composition, RMI declarations), or rely on descriptions, which only catch parts named after a material.

## Keeping it private
The file is processed in memory and not stored. If policy forbids uploading it, run the platform in your own network (Docker) and use the API: `POST /api/v1/company/analyze` with the CSV as the body.
