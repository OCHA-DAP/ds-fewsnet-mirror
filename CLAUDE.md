# ds-fewsnet-mirror

Mirror of FEWS NET IPC-compatible acute food insecurity classifications into
the team **dev** Postgres (schema **`fewsnet`**) + dev blob (unit geometry).
GH Pages explorer deployed from Actions. Modeled 1:1 on `ds-ipc-mirror`.

## Key facts

- Source: FDW API (`fdw.fews.net/api`), no auth. Per-country
  `ipcphase.csv?country_code=<ISO2>` (CSV streams the full record fast; the
  JSON API caps page_size at 500 and is far too slow for 1.3M rows) +
  `ipcpackage/?country_code=<ISO2>` (zip of the LATEST round's shapefiles).
  Coverage is discovered by probing all ~252 FDW countries; ~45 have data.
- Tables: `fewsnet.classification` (full-replace with a refuse-to-shrink
  guard) and `fewsnet.units` (upsert on FNID — old FNID vintages are kept;
  their geometry is not re-fetched). Geometry goes to dev blob
  `projects/ds-fewsnet-mirror/processed/units/{ISO3}.geojson`, uploaded only
  when a country's `report_mon` round moves on.
- **Keying**: (fnid, scenario, projection_start, reporting_date).
  `reporting_date` = collection round (FSO ~3×/yr + FSO Updates + monthly Key
  Message Updates + FAOB); projection window = what the phase is valid FOR.
  Rounds overlap in time — never build a series without keying on both.
- **FNIDs are FEWS NET's own geography** (fsc_admin_lhz / fsc_admin /
  idp_camp / national_park / admin0), vintage encoded in the FNID
  (UG2026C3…). No COD p-codes anywhere; join to our boundaries via the
  package's ADMIN1/ADMIN2 name columns.
- **`assistance` is the "!" marker, not a series**: one published row per
  (fnid, scenario, round); True = drawn with "!" (phase held down by
  assistance). Never filter on it — filtering `assistance = false` drops the
  "!" units (verified against the Oct 2016 ZW package HA0/HA1/HA2 fields).
- **Absent is not Phase 1**: `phase` null + status Not Projected/Not
  Available = not classified. Shapefile sentinels 66/88/99 (water/park/no
  data) arrive as null + status via the CSV.
- Scales: "IPC 3.1"/"IPC 3.0"/"IPC 2.0" (era-dependent) on subnational units;
  "IPC Highest Household" is the national FAOB series (unit_type admin0) —
  filter it out for maps.
- No population-in-phase anywhere public; FDW `ipcpopulation` is a national
  FAOB phase-3+ series only (not mirrored).
- Only `data_usage_policy == "Public"` rows are mirrored (site republishes).
- DB access via `ocha_stratus.get_engine(stage=STAGE, write=…)`;
  `PGSSLMODE=require`. Blob via `stratus.upload_blob_data` (needs
  `DSCI_AZ_BLOB_DEV_SAS_WRITE`).
- GHA: `DSCI_AZ_DB_*` / `DSCI_AZ_BLOB_*` are OCHA-DAP **org-level** secrets.
  No FDW key needed.
- CI pins Python 3.12; installs with `uv pip install --no-sources -e .`.
- Workflows: `refresh-fewsnet.yml` (daily) → `deploy-site.yml` chains via
  `workflow_run`, regenerates `site/data/*.json` from the DB (git-ignored).
- Downstream: seas5-skill Forecast × HNRP tab (FEWS NET severity source).
- KB pages: `pipelines/fewsnet-mirror.md`, `infrastructure/datasets/fews-net.md`.
