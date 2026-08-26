"""Export DB contents to static JSON for the GitHub Pages explorer.

Writes site/data/index.json plus per-country
site/data/classification/{ISO3}.json and site/data/units/{ISO3}.json
(compact arrays).
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

import pandas as pd  # noqa: E402

from src import storage  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SITE_DATA = Path(__file__).parent.parent / "site" / "data"

CLASS_ROW_COLS = [
    "fnid", "unit_name", "unit_type", "scale", "scenario", "assistance",
    "reporting_date", "projection_start", "projection_end",
    "source_document", "status", "phase", "description",
]
UNIT_ROW_COLS = [
    "fnid", "unit_name", "admin1", "admin2", "lzname", "unit_type", "report_mon",
]


def _clean(v):
    if pd.isna(v):
        return None
    if isinstance(v, float) and v == int(v):
        return int(v)
    if isinstance(v, bool):
        return int(v)
    return str(v) if hasattr(v, "isoformat") else v


def _rows(df, cols):
    return [
        [_clean(v) for v in row]
        for row in df[cols].itertuples(index=False, name=None)
    ]


def main():
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    cls = storage.read_classification()
    units = storage.read_units()

    (SITE_DATA / "classification").mkdir(exist_ok=True)
    for iso3, g in sorted(cls.groupby("iso3")):
        g = g.sort_values(["reporting_date", "fnid"], ascending=[False, True])
        (SITE_DATA / "classification" / f"{iso3}.json").write_text(
            json.dumps(
                {
                    "generated_at": generated_at,
                    "iso3": iso3,
                    "columns": CLASS_ROW_COLS,
                    "rows": _rows(g, CLASS_ROW_COLS),
                }
            )
        )

    (SITE_DATA / "units").mkdir(exist_ok=True)
    for iso3, g in sorted(units.groupby("iso3")):
        (SITE_DATA / "units" / f"{iso3}.json").write_text(
            json.dumps(
                {
                    "generated_at": generated_at,
                    "iso3": iso3,
                    "columns": UNIT_ROW_COLS,
                    "rows": _rows(g.sort_values("fnid"), UNIT_ROW_COLS),
                }
            )
        )

    unit_isos = set(units["iso3"].unique())
    countries = []
    for iso3, g in sorted(cls.groupby("iso3")):
        countries.append(
            {
                "iso3": iso3,
                "country": g["country"].iloc[0],
                "rounds": sorted({str(d) for d in g["reporting_date"].dropna()},
                                 reverse=True)[:60],
                "n_rows": len(g),
                "has_units": iso3 in unit_isos,
            }
        )
    (SITE_DATA / "index.json").write_text(
        json.dumps({"generated_at": generated_at, "countries": countries})
    )
    logger.info(
        "index.json: %s countries (%s with unit geometry)",
        len(countries), len(unit_isos),
    )


if __name__ == "__main__":
    main()
