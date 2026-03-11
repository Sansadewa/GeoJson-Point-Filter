#!/usr/bin/env python3
"""
One-time script to import per-kabupaten GeoJSON files into the
desa_boundaries PostGIS table in Supabase.

GeoJSON feature properties expected:
    kdprov, kdkab, kdkec, kddesa  (codes)
    nmprov, nmkab, nmkec, nmdesa  (names)
Extra properties (fid, gid, iddesa, luas, etc.) are ignored.

Usage:
    # Preview what would be imported (no writes)
    python scripts/import_boundaries.py ./polygons/ --dry-run

    # Import all files
    python scripts/import_boundaries.py ./polygons/

Reads Supabase credentials from .streamlit/secrets.toml
"""

import sys
import json
import glob
import re
from pathlib import Path

import geopandas as gpd
from shapely.geometry import mapping, MultiPolygon, Polygon
from supabase import create_client

# Properties to extract from each GeoJSON feature
REQUIRED_PROPS = ["kdprov", "kdkab", "kdkec", "kddesa", "nmprov", "nmkab", "nmkec", "nmdesa"]

BATCH_SIZE = 100


def load_secrets():
    """Load Supabase credentials from .streamlit/secrets.toml (pure-regex TOML parser)."""
    secrets_path = Path(__file__).parent.parent / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        print(f"ERROR: {secrets_path} not found")
        print("Create .streamlit/secrets.toml with [supabase] url and key.")
        sys.exit(1)
    text = secrets_path.read_text()
    # Extract values under [supabase] section using simple regex
    url_m = re.search(r'url\s*=\s*"([^"]+)"', text)
    key_m = re.search(r'key\s*=\s*"([^"]+)"', text)
    if not url_m or not key_m:
        print("ERROR: secrets.toml must have [supabase] section with url and key")
        sys.exit(1)
    return url_m.group(1), key_m.group(1)


def ensure_multipolygon(geom):
    """Normalise any geometry to MultiPolygon, required by the table schema."""
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    if isinstance(geom, MultiPolygon):
        return geom
    raise ValueError(f"Unsupported geometry type: {geom.geom_type}")


def import_file(supabase_client, filepath, dry_run=False):
    """
    Read a single GeoJSON file and insert its rows into desa_boundaries.
    Returns the number of rows inserted (or that would be inserted).
    """
    print(f"  Reading {Path(filepath).name} ...", end=" ", flush=True)
    gdf = gpd.read_file(filepath)

    # Ensure CRS is EPSG:4326
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    # Verify required columns exist
    missing = [c for c in REQUIRED_PROPS if c not in gdf.columns]
    if missing:
        print(f"SKIP (missing columns: {missing})")
        return 0

    rows = []
    skipped_geom = 0
    for _, row in gdf.iterrows():
        try:
            geom = ensure_multipolygon(row.geometry)
        except (ValueError, AttributeError):
            skipped_geom += 1
            continue

        record = {prop: str(row[prop]) if row[prop] is not None else "" for prop in REQUIRED_PROPS}
        # PostGIS expects WKT or GeoJSON; supabase-py sends JSON to PostgREST.
        # We encode geometry as GeoJSON string for the `geom` column.
        record["geom"] = json.dumps(mapping(geom))
        rows.append(record)

    print(f"{len(rows)} rows", end="")
    if skipped_geom:
        print(f" ({skipped_geom} skipped - bad geometry)", end="")
    print()

    if dry_run or not rows:
        return len(rows)

    # Batch insert
    inserted = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        try:
            supabase_client.table("desa_boundaries").insert(batch).execute()
            inserted += len(batch)
        except Exception as e:
            print(f"    ERROR inserting batch {i}–{i + len(batch)}: {e}")
            # Show first record for debugging (omit geom string)
            debug = {k: v for k, v in batch[0].items() if k != "geom"}
            print(f"    First record: {debug}")
            raise

    return inserted


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    folder = Path(sys.argv[1])
    dry_run = "--dry-run" in sys.argv

    if not folder.exists() or not folder.is_dir():
        print(f"ERROR: Folder not found: {folder}")
        sys.exit(1)

    # Collect GeoJSON files
    files = sorted(glob.glob(str(folder / "*.geojson")))
    if not files:
        files = sorted(glob.glob(str(folder / "*.json")))
    if not files:
        print(f"ERROR: No .geojson or .json files found in {folder}")
        sys.exit(1)

    print(f"Found {len(files)} file(s) in {folder}/")

    # Preview first file to confirm schema
    preview_gdf = gpd.read_file(files[0])
    print(f"\nFirst file: {Path(files[0]).name}")
    print(f"  Columns : {list(preview_gdf.columns)}")
    print(f"  Rows    : {len(preview_gdf)}")
    if not preview_gdf.empty:
        sample = {k: preview_gdf.iloc[0][k] for k in REQUIRED_PROPS if k in preview_gdf.columns}
        print(f"  Sample  : {sample}")

    missing_top = [c for c in REQUIRED_PROPS if c not in preview_gdf.columns]
    if missing_top:
        print(f"\nERROR: Required columns missing from files: {missing_top}")
        print("Expected columns:", REQUIRED_PROPS)
        sys.exit(1)

    if dry_run:
        print("\n=== DRY RUN — no data will be written ===\n")
    else:
        print()

    url, key = load_secrets()
    supabase_client = create_client(url, key)

    total = 0
    errors = 0
    for filepath in files:
        try:
            count = import_file(supabase_client, filepath, dry_run=dry_run)
            total += count
        except Exception:
            errors += 1

    action = "Would insert" if dry_run else "Inserted"
    print(f"\n{'='*50}")
    print(f"{action}: {total:,} desa boundaries from {len(files)} file(s)")
    if errors:
        print(f"Errors   : {errors} file(s) failed")
    print(f"{'='*50}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
