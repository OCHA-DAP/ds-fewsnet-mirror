# ds-fewsnet-mirror

Daily mirror of **FEWS NET's IPC-compatible acute food insecurity
classifications** (FDW API) into the CHD DS team Postgres (dev, schema
`fewsnet`) and dev blob, with a
[GitHub Pages explorer](https://ocha-dap.github.io/ds-fewsnet-mirror/).

FEWS NET ≠ IPC: FEWS NET's classifications are IPC-*compatible* but are FEWS
NET's own analysis and can disagree with the [IPC/CH
consensus](https://github.com/OCHA-DAP/ds-ipc-mirror). Deliberately mirrored
separately.

| output | source | granularity |
|---|---|---|
| `fewsnet.classification` (DB) | FDW `ipcphase.csv` per country | one row per FNID unit × scenario (CS/ML1/ML2) × collection round, 2009+ |
| `fewsnet.units` (DB) | FDW `ipcpackage` per country | latest round's unit registry: FNID, admin 0–3 names, livelihood zone |
| `projects/ds-fewsnet-mirror/processed/units/{ISO3}.geojson` (dev blob) | same package shapefiles | latest round's unit **geometry**, one feature per FNID |

Key facts:

- Units are FEWS NET's **own geography** (FNIDs): livelihood-zone × admin
  intersections, admin units, IDP camps, national parks — **no COD p-codes,
  no population-in-phase figures** (FEWS NET classifies areas).
- Every row keys on **both** the collection round (`reporting_date`) and the
  projection window (`projection_start/end`) — a later round's *current*
  overlaps an earlier round's *projection*.
- `assistance` (FDW `is_allowing_for_assistance`) is the "!" marker on the ONE
  published row per (fnid, scenario, round): True = FEWS NET draws the unit with
  "!" (phase held down by humanitarian assistance). It is NOT a parallel series
  — never filter on it; count every row at its phase. (Verified 2026-09-16
  against the Oct 2016 ZW package shapefiles' HA0/HA1/HA2 fields; the earlier
  "published map = assistance=false" reading dropped the "!" units.)
- `phase` is null with `status` "Not Projected" / "Not Available" where FEWS
  NET did not classify — **absent is not Phase 1**. Shapefile sentinels
  (66 water / 88 parks / 99 no data) appear as null + status here.

## Pipelines (Databricks + GitHub Pages)

The dev DB is reachable only through its private endpoint, so the refresh and
the site-data export run on Databricks; GitHub Actions only deploys the site.

- **FEWS NET Mirror** (Databricks job, `databricks.yml`) — daily 04:52 UTC: `refresh_fewsnet.py`, then `export_site_data.py`, then parks `site/data/` on the dev blob (`projects/ds-fewsnet-mirror/site-data/`, `scripts/site_data_blob.py upload`).
- **Deploy explorer site** (`deploy-site.yml`) — daily 08:30 UTC (and on dispatch): copies `site/data/` down from the blob and deploys `site/` to GitHub Pages. Output identical to when the export ran in the workflow.

```sh
databricks bundle validate -t prod -p DEFAULT
databricks bundle deploy   -t prod -p DEFAULT   # config changes only; code ships by pushing main
```

## Run locally

```sh
uv sync
cp .env.example .env  # fill in creds
uv run python scripts/refresh_fewsnet.py            # full refresh (~30 min)
uv run python scripts/refresh_fewsnet.py --only UGA # geometry/units test run
uv run python scripts/export_site_data.py
```

## License / attribution

FEWS NET data is public (USAID). Attribution: "Source: FEWS NET" —
[fews.net/data](https://fews.net/data).
