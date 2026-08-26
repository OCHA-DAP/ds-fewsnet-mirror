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
- The published map is the `assistance = false` series ("not allowing for
  assistance", preference-rated 90/85); `assistance = true` rows exist only
  for units where factoring assistance out changes the phase (verified
  against the package shapefiles, which are the rendered map).
- `phase` is null with `status` "Not Projected" / "Not Available" where FEWS
  NET did not classify — **absent is not Phase 1**. Shapefile sentinels
  (66 water / 88 parks / 99 no data) appear as null + status here.

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
