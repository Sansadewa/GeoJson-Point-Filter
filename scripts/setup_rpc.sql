-- =============================================================
-- GeoJSON Point Filter - Supabase RPC Functions
-- Run this entire file in the Supabase SQL Editor.
-- Requires the desa_boundaries table and PostGIS extension.
-- =============================================================

-- Enable PostGIS if not already enabled
CREATE EXTENSION IF NOT EXISTS postgis;

-- -------------------------------------------------------------
-- get_regions
-- Returns distinct region names and codes at a given
-- administrative level, optionally filtered by parent codes.
--
-- Usage:
--   get_regions('provinsi')
--   get_regions('kabupaten', p_kdprov => '63')
--   get_regions('kecamatan', p_kdprov => '63', p_kdkab => '01')
--   get_regions('desa', p_kdprov => '63', p_kdkab => '01', p_kdkec => '040')
-- -------------------------------------------------------------
CREATE OR REPLACE FUNCTION get_regions(
    p_level  TEXT,
    p_kdprov TEXT DEFAULT NULL,
    p_kdkab  TEXT DEFAULT NULL,
    p_kdkec  TEXT DEFAULT NULL
)
RETURNS TABLE(kode TEXT, nama TEXT)
LANGUAGE plpgsql STABLE
AS $$
BEGIN
    IF p_level = 'provinsi' THEN
        RETURN QUERY
            SELECT DISTINCT b.kdprov, b.nmprov
            FROM desa_boundaries b
            ORDER BY b.nmprov;

    ELSIF p_level = 'kabupaten' THEN
        RETURN QUERY
            SELECT DISTINCT b.kdkab, b.nmkab
            FROM desa_boundaries b
            WHERE b.kdprov = p_kdprov
            ORDER BY b.nmkab;

    ELSIF p_level = 'kecamatan' THEN
        RETURN QUERY
            SELECT DISTINCT b.kdkec, b.nmkec
            FROM desa_boundaries b
            WHERE b.kdprov = p_kdprov
              AND b.kdkab  = p_kdkab
            ORDER BY b.nmkec;

    ELSIF p_level = 'desa' THEN
        RETURN QUERY
            SELECT DISTINCT b.kddesa, b.nmdesa
            FROM desa_boundaries b
            WHERE b.kdprov = p_kdprov
              AND b.kdkab  = p_kdkab
              AND b.kdkec  = p_kdkec
            ORDER BY b.nmdesa;
    END IF;
END;
$$;


-- -------------------------------------------------------------
-- get_boundary_geojson
-- Returns a single dissolved GeoJSON geometry (ST_Union of all
-- desa polygons matching the provided filter codes).
-- Stopping at any level automatically merges child polygons.
--
-- Usage:
--   get_boundary_geojson(p_kdprov => '63')               -- whole provinsi
--   get_boundary_geojson(p_kdprov => '63', p_kdkab => '01')  -- one kabupaten
--   get_boundary_geojson(p_kdprov => '63', p_kdkab => '01', p_kdkec => '040')
--   get_boundary_geojson(p_kdprov => '63', p_kdkab => '01', p_kdkec => '040', p_kddesa => '006')
-- -------------------------------------------------------------
CREATE OR REPLACE FUNCTION get_boundary_geojson(
    p_kdprov TEXT DEFAULT NULL,
    p_kdkab  TEXT DEFAULT NULL,
    p_kdkec  TEXT DEFAULT NULL,
    p_kddesa TEXT DEFAULT NULL
)
RETURNS JSON
LANGUAGE sql STABLE
AS $$
    SELECT ST_AsGeoJSON(ST_Union(geom))::json
    FROM desa_boundaries
    WHERE (p_kdprov IS NULL OR kdprov = p_kdprov)
      AND (p_kdkab  IS NULL OR kdkab  = p_kdkab)
      AND (p_kdkec  IS NULL OR kdkec  = p_kdkec)
      AND (p_kddesa IS NULL OR kddesa = p_kddesa);
$$;
