"""
Supabase client module for GeoJSON Point Filter.

Provides cached functions to:
- Fetch distinct administrative region lists (for cascading dropdowns)
- Fetch a dissolved boundary polygon for a selected region
- Fetch coordinate data from sbr_data filtered by region codes

All public functions use Streamlit caching so repeated calls within
a session don't round-trip to the database.
"""

import streamlit as st
import pandas as pd
import geopandas as gpd
from shapely.geometry import shape


@st.cache_resource
def get_client():
    """
    Initialise and cache the Supabase client for the session lifetime.
    Reads credentials from .streamlit/secrets.toml:
        [supabase]
        url = "https://..."
        key = "..."
    """
    from supabase import create_client
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)


@st.cache_data(ttl=600)
def fetch_regions(level: str, kdprov: str | None = None, kdkab: str | None = None, kdkec: str | None = None) -> list[dict]:
    """
    Return distinct region entries at the requested administrative level.

    Args:
        level:   'provinsi' | 'kabupaten' | 'kecamatan' | 'desa'
        kdprov:  Province code  (required for kabupaten / kecamatan / desa)
        kdkab:   Kabupaten code (required for kecamatan / desa)
        kdkec:   Kecamatan code (required for desa)

    Returns:
        List of dicts with keys 'kode' and 'nama', sorted by nama.
        Empty list on error or when no data is found.
    """
    try:
        client = get_client()
        result = client.rpc("get_regions", {
            "p_level":  level,
            "p_kdprov": kdprov,
            "p_kdkab":  kdkab,
            "p_kdkec":  kdkec,
        }).execute()
        return result.data or []
    except Exception as e:
        st.error(f"Failed to fetch {level} list: {e}")
        return []


@st.cache_data(ttl=300)
def fetch_boundary(
    kdprov: str,
    kdkab:  str | None = None,
    kdkec:  str | None = None,
    kddesa: str | None = None,
) -> gpd.GeoDataFrame | None:
    """
    Fetch the dissolved boundary polygon for a selected region.

    Passes only the supplied codes to `get_boundary_geojson`; the SQL
    function does ST_Union over all matching desa polygons, so selecting
    only a provinsi merges the entire provinsi into one shape.

    Args:
        kdprov:  Province code (required)
        kdkab:   Kabupaten code (optional – narrows to kabupaten level)
        kdkec:   Kecamatan code (optional – narrows to kecamatan level)
        kddesa:  Desa code      (optional – single desa polygon)

    Returns:
        Single-row GeoDataFrame in EPSG:4326, or None on error / no match.
    """
    try:
        client = get_client()
        result = client.rpc("get_boundary_geojson", {
            "p_kdprov": kdprov,
            "p_kdkab":  kdkab,
            "p_kdkec":  kdkec,
            "p_kddesa": kddesa,
        }).execute()

        geojson = result.data
        if not geojson:
            return None

        geom = shape(geojson)
        return gpd.GeoDataFrame(geometry=[geom], crs="EPSG:4326")

    except Exception as e:
        st.error(f"Failed to fetch boundary: {e}")
        return None


@st.cache_data(ttl=300)
def fetch_sbr_data(
    kdprov: str,
    kdkab:  str | None = None,
    kdkec:  str | None = None,
    kddesa: str | None = None,
) -> tuple[pd.DataFrame, int]:
    """
    Fetch rows from the sbr_data table filtered by region codes.

    Uses paginated requests (1 000 rows each) to work around the
    PostgREST default row-limit, so the full result set is always
    returned regardless of size.

    Args:
        kdprov:  Province code (required)
        kdkab:   Kabupaten code (optional)
        kdkec:   Kecamatan code (optional)
        kddesa:  Desa code      (optional)

    Returns:
        Tuple of (DataFrame, total_count). Empty DataFrame with count 0
        on error or when no rows match.
    """
    PAGE_SIZE = 1_000
    try:
        client = get_client()

        def _base_query():
            q = client.table("sbr_data").select("*").eq("kdprov", kdprov)
            if kdkab:
                q = q.eq("kdkab", kdkab)
            if kdkec:
                q = q.eq("kdkec", kdkec)
            if kddesa:
                q = q.eq("kddesa", kddesa)
            return q

        all_rows = []
        offset = 0
        while True:
            result = _base_query().range(offset, offset + PAGE_SIZE - 1).execute()
            batch = result.data or []
            all_rows.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE

        if not all_rows:
            return pd.DataFrame(), 0

        return pd.DataFrame(all_rows), len(all_rows)

    except Exception as e:
        st.error(f"Failed to fetch sbr_data: {e}")
        return pd.DataFrame(), 0
