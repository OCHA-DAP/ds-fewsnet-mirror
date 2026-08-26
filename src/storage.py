"""DB + blob layer: fewsnet schema on the team Postgres, geometry on dev blob.

Stage is selected with the STAGE env var (default "dev"). Writers need the
*_UID_WRITE / *_PW_WRITE credentials; PGSSLMODE=require is enforced here.
Unit geometry (FEWS NET's own FNID-keyed polygons) does not go in the DB —
each country's latest-round units land as one GeoJSON in the dev `projects`
container under ds-fewsnet-mirror/processed/units/{ISO3}.geojson.
"""

import json
import logging
import os
from datetime import datetime, timezone

os.environ.setdefault("PGSSLMODE", "require")

import ocha_stratus as stratus
import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)

SCHEMA = "fewsnet"
STAGE = os.environ.get("STAGE", "dev")
BLOB_PREFIX = "ds-fewsnet-mirror/processed/units"

CLASSIFICATION_COLS = [
    "iso3", "iso2", "country", "fnid", "unit_name", "unit_full_name",
    "unit_type", "geographic_unit", "scale", "scenario", "scenario_name",
    "assistance", "projection_start", "projection_end", "reporting_date",
    "source_document", "document_type", "collection", "collection_period",
    "status", "collection_status", "phase", "description",
    "pct_phase3", "pct_phase4", "pct_phase5", "source_id", "created", "modified",
]
UNIT_COLS = [
    "fnid", "iso3", "iso2", "unit_name", "admin0", "admin1", "admin2",
    "admin3", "lzcode", "lzname", "unit_type", "report_mon",
]


def get_engine(write=False):
    return stratus.get_engine(stage=STAGE, write=write)


def ensure_tables():
    ddl = f"""
    CREATE SCHEMA IF NOT EXISTS {SCHEMA};
    CREATE TABLE IF NOT EXISTS {SCHEMA}.classification (
        iso3 text,
        iso2 text,
        country text,
        fnid text,
        unit_name text,
        unit_full_name text,
        unit_type text,
        geographic_unit bigint,
        scale text,
        scenario text,
        scenario_name text,
        assistance boolean,
        projection_start date,
        projection_end date,
        reporting_date date,
        source_document text,
        document_type text,
        collection bigint,
        collection_period bigint,
        status text,
        collection_status text,
        phase double precision,
        description text,
        pct_phase3 double precision,
        pct_phase4 double precision,
        pct_phase5 double precision,
        source_id bigint,
        created timestamptz,
        modified timestamptz,
        refreshed_at timestamptz
    );
    CREATE INDEX IF NOT EXISTS classification_key_idx
        ON {SCHEMA}.classification (iso3, scenario, reporting_date);
    CREATE INDEX IF NOT EXISTS classification_fnid_idx
        ON {SCHEMA}.classification (fnid);
    CREATE TABLE IF NOT EXISTS {SCHEMA}.units (
        fnid text PRIMARY KEY,
        iso3 text,
        iso2 text,
        unit_name text,
        admin0 text,
        admin1 text,
        admin2 text,
        admin3 text,
        lzcode text,
        lzname text,
        unit_type text,
        report_mon date,
        refreshed_at timestamptz
    );
    CREATE INDEX IF NOT EXISTS units_iso3_idx ON {SCHEMA}.units (iso3);
    """
    with get_engine(write=True).begin() as conn:
        conn.execute(text(ddl))


def replace_classification(df, guard=0.5):
    """Full transactional replace, refusing to shrink the table by > guard."""
    df = df[CLASSIFICATION_COLS].copy()
    df["refreshed_at"] = datetime.now(timezone.utc)
    engine = get_engine(write=True)
    with engine.begin() as conn:
        existing = conn.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.classification")
        ).scalar()
        if existing and len(df) < existing * guard:
            raise RuntimeError(
                f"classification: refusing to replace {existing} rows with "
                f"{len(df)} (partial pull?)"
            )
        conn.execute(text(f"DELETE FROM {SCHEMA}.classification"))
        df.to_sql(
            "classification",
            conn,
            schema=SCHEMA,
            if_exists="append",
            index=False,
            chunksize=10_000,
            method="multi",
        )
    logger.info("Replaced %s.classification with %s rows", SCHEMA, len(df))


def unit_round_of(iso3):
    """Latest report_mon currently held for a country ('' when none)."""
    with get_engine().connect() as conn:
        v = conn.execute(
            text(f"SELECT max(report_mon) FROM {SCHEMA}.units WHERE iso3 = :i"),
            {"i": iso3},
        ).scalar()
    return str(v) if v else ""


def upsert_units(df):
    if df is None or df.empty:
        return
    df = df[UNIT_COLS].copy()
    df["refreshed_at"] = datetime.now(timezone.utc)
    df = df.astype(object).where(pd.notna(df), None)
    cols = UNIT_COLS + ["refreshed_at"]
    collist = ", ".join(cols)
    params = ", ".join(f":{c}" for c in cols)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "fnid")
    sql = text(
        f"INSERT INTO {SCHEMA}.units ({collist}) VALUES ({params}) "
        f"ON CONFLICT (fnid) DO UPDATE SET {updates}"
    )
    with get_engine(write=True).begin() as conn:
        conn.execute(sql, df.to_dict("records"))
    logger.info("Upserted %s units (%s)", len(df), df["iso3"].iloc[0])


def upload_geojson(iso3, features):
    payload = json.dumps(
        {"type": "FeatureCollection", "features": features},
        separators=(",", ":"),
    ).encode()
    stratus.upload_blob_data(
        payload,
        f"{BLOB_PREFIX}/{iso3}.geojson",
        stage=STAGE,
        content_type="application/geo+json",
    )
    logger.info("Uploaded %s/%s.geojson (%.1f MB)",
                BLOB_PREFIX, iso3, len(payload) / 1e6)


def read_classification():
    return pd.read_sql(f"SELECT * FROM {SCHEMA}.classification", get_engine())


def read_units():
    return pd.read_sql(f"SELECT * FROM {SCHEMA}.units", get_engine())
