"""Refresh the FEWS NET mirror: FDW ipcphase per country + latest unit geometry.

Coverage is discovered, not hardcoded: every ISO country FDW knows is probed
and the ~45 with classification rows are kept. Geometry (the latest collection
round's package) is re-fetched only when a country's round moved on, so the
daily run uploads nothing on quiet days.
"""

import argparse
import logging
import sys

sys.path.insert(0, ".")

import pandas as pd
from dotenv import load_dotenv

from src import fdw, storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logging.getLogger("azure").setLevel(logging.WARNING)
logger = logging.getLogger("refresh_fewsnet")


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Comma-separated ISO3 list (testing); skips "
                                   "the classification-table replace guard scope "
                                   "by refreshing geometry/units only")
    ap.add_argument("--skip-geometry", action="store_true",
                    help="Refresh the classification table only")
    args = ap.parse_args()

    storage.ensure_tables()
    countries = fdw.list_countries()
    if args.only:
        keep = {c.strip().upper() for c in args.only.split(",")}
        countries = [c for c in countries if c["iso3"] in keep]
    logger.info("Probing %s countries", len(countries))

    frames = []
    for c in countries:
        try:
            df = fdw.fetch_classification(c["iso2"], c["iso3"])
        except Exception:
            logger.exception("%s: classification fetch failed — skipped", c["iso3"])
            continue
        if df is None:
            continue
        logger.info("%s: %s classification rows", c["iso3"], len(df))
        frames.append(df)
    if not frames:
        sys.exit("No classification rows fetched — refusing to continue")
    classification = pd.concat(frames, ignore_index=True)
    if args.only:
        logger.info("--only run: NOT replacing the classification table "
                    "(%s rows fetched)", len(classification))
    else:
        storage.replace_classification(classification)

    if args.skip_geometry:
        return
    have = set(classification["iso3"].unique())
    covered = sorted((c["iso2"], c["iso3"]) for c in countries if c["iso3"] in have)
    for iso2, iso3 in covered:
        held = storage.unit_round_of(iso3)
        try:
            units, feats = fdw.fetch_package(iso2, iso3)
        except Exception:
            logger.exception("%s: package fetch failed — skipped", iso3)
            continue
        if units is None:
            logger.info("%s: no geometry package", iso3)
            continue
        new_round = str(units["report_mon"].max() or "")
        if held and new_round and new_round <= held:
            logger.info("%s: geometry round %s already held — skipped", iso3, held)
            continue
        storage.upsert_units(units)
        storage.upload_geojson(iso3, feats)

    logger.info("Refresh complete")


if __name__ == "__main__":
    main()
