"""Ingest FEWS NET classifications from the FDW API (fdw.fews.net).

Two payloads per country, discovered by probing every ISO country FDW knows:

- `ipcphase.csv?country_code=XX` — the full record of FEWS NET's IPC-compatible
  acute food insecurity classifications: one row per geographic unit x scenario
  (CS / ML1 / ML2) x collection round, 2009+ where published. FEWS NET's units
  are its OWN geography (FNIDs): livelihood-zone x admin intersections
  (fsc_admin_lhz), admin units (fsc_admin), IDP camps, national parks — NOT COD
  p-coded admin units, and the unit vintage is encoded in the FNID.
- `ipcpackage/?country_code=XX` — a zip of the LATEST collection round's
  shapefiles (one per scenario), which is where unit geometry and the
  admin/livelihood-zone attributes live. Historical rounds' geometry is not
  re-fetched: FNID vintages change rarely and the package always carries the
  units current classifications sit on.

Row key in ipcphase: (fnid, scenario, projection_start, reporting_date).
`reporting_date` is the collection round (a Food Security Outlook, Outlook
Update, or Key Message Update); the projection window is what the phase is
valid FOR — like IPC, a later round's current overlaps an earlier round's
projection, so never build a time series without keying on both.

FEWS NET data is public (USAID; attribution required). Only rows with
data_usage_policy == "Public" are mirrored.
"""

import io
import logging
import time
import zipfile

import pandas as pd
import requests
import shapefile  # pyshp

logger = logging.getLogger(__name__)

BASE = "https://fdw.fews.net/api"

# ipcphase CSV column -> mirror column. Everything else is dropped.
CLASSIFICATION_RENAME = {
    "country_code": "iso2",
    "country": "country",
    "fnid": "fnid",
    "geographic_unit_name": "unit_name",
    "geographic_unit_full_name": "unit_full_name",
    "unit_type": "unit_type",
    "geographic_unit": "geographic_unit",
    "classification_scale": "scale",
    "scenario": "scenario",
    "scenario_name": "scenario_name",
    "is_allowing_for_assistance": "assistance",
    "projection_start": "projection_start",
    "projection_end": "projection_end",
    "reporting_date": "reporting_date",
    "source_document": "source_document",
    "document_type": "document_type",
    "datacollection": "collection",
    "datacollectionperiod": "collection_period",
    "status": "status",
    "collection_status": "collection_status",
    "value": "phase",
    "description": "description",
    "pct_phase3": "pct_phase3",
    "pct_phase4": "pct_phase4",
    "pct_phase5": "pct_phase5",
    "id": "source_id",
    "created": "created",
    "modified": "modified",
}


def _get(url, **kwargs):
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=300, **kwargs)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(10 * (attempt + 1))


def list_countries():
    """All countries FDW knows, as [{'iso2':…, 'iso3':…, 'name':…}]."""
    out, offset = [], 0
    while True:
        r = _get(f"{BASE}/country/",
                 params={"format": "json", "page_size": 500, "offset": offset})
        d = r.json()
        for row in d["results"]:
            if row.get("iso3166a2") and row.get("iso3166a3"):
                out.append({"iso2": row["iso3166a2"], "iso3": row["iso3166a3"],
                            "name": row.get("preferred_name")})
        if not d.get("next"):
            return out
        offset += 500


def fetch_classification(iso2, iso3):
    """One country's full ipcphase record, normalized; None when uncovered."""
    r = _get(f"{BASE}/ipcphase.csv", params={"country_code": iso2})
    df = pd.read_csv(io.BytesIO(r.content), encoding="utf-8-sig", low_memory=False)
    if df.empty or "fnid" not in df.columns:
        return None
    nonpublic = df["data_usage_policy"] != "Public"
    if nonpublic.any():
        logger.warning("%s: %s non-Public row(s) dropped", iso2, int(nonpublic.sum()))
        df = df[~nonpublic]
    df = df[[c for c in CLASSIFICATION_RENAME if c in df.columns]].rename(
        columns=CLASSIFICATION_RENAME)
    df["iso3"] = iso3
    for col in ("projection_start", "projection_end", "reporting_date"):
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    df = df.drop_duplicates(subset=["source_id"])
    return df


def _round_coords(obj, ndigits=6):
    if isinstance(obj, (list, tuple)):
        return [_round_coords(v, ndigits) for v in obj]
    if isinstance(obj, float):
        return round(obj, ndigits)
    return obj


def fetch_package(iso2, iso3):
    """The latest collection round's unit geometry for one country.

    Returns (units_df, geojson_features) or (None, None) when there is no
    package. Scenario shapefiles in the zip (CS/ML1/ML2, plus *_IDP point
    layers) repeat the same units — features are deduped on FNID; per-scenario
    phase values are NOT taken from here (they live in the classification
    table), only identity, admin/livelihood-zone attributes and geometry.
    """
    r = _get(f"{BASE}/ipcpackage/", params={"country_code": iso2})
    if len(r.content) < 100:  # empty zip: country not covered
        return None, None
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    rows, feats, seen = [], [], set()
    for name in sorted(zf.namelist()):
        if not name.endswith(".shp"):
            continue
        stem = name[:-4]
        try:
            reader = shapefile.Reader(
                shp=io.BytesIO(zf.read(stem + ".shp")),
                dbf=io.BytesIO(zf.read(stem + ".dbf")),
                shx=io.BytesIO(zf.read(stem + ".shx")),
            )
        except Exception:
            logger.exception("%s: failed to read %s — skipped", iso2, name)
            continue
        fields = [f[0] for f in reader.fields[1:]]
        for sr in reader.iterShapeRecords():
            rec = dict(zip(fields, sr.record))
            fnid = rec.get("fnid")
            if not fnid or fnid in seen:
                continue
            seen.add(fnid)
            report_mon = rec.get("report_mon")  # "MM-YYYY"
            try:
                m, y = str(report_mon).split("-")
                report_mon = f"{y}-{m}-01"
            except ValueError:
                report_mon = None
            row = {
                "fnid": fnid,
                "iso3": iso3,
                "iso2": iso2,
                "unit_name": rec.get("unit_name"),
                "admin0": rec.get("ADMIN0"),
                "admin1": rec.get("ADMIN1"),
                "admin2": rec.get("ADMIN2"),
                "admin3": rec.get("ADMIN3"),
                "lzcode": rec.get("LZCODE"),
                "lzname": rec.get("LZNAME"),
                "unit_type": rec.get("unit_type"),
                "report_mon": report_mon,
            }
            rows.append(row)
            geom = sr.shape.__geo_interface__
            feats.append({
                "type": "Feature",
                "properties": {k: v for k, v in row.items() if k != "report_mon"},
                "geometry": {"type": geom["type"],
                             "coordinates": _round_coords(geom["coordinates"])},
            })
    if not rows:
        return None, None
    return pd.DataFrame(rows), feats
