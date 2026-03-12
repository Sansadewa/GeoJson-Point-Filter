-- =========================================================================
-- sbr_data Table Setup for GeoJSON Point Filter
-- 
-- Run this in the Supabase SQL Editor:
-- https://supabase.com/dashboard/project/[YOUR_PROJECT]/sql
-- =========================================================================

-- Create sbr_data table with the business registry schema
CREATE TABLE IF NOT EXISTS sbr_data (
    id BIGSERIAL PRIMARY KEY,
    idsbr TEXT,
    nama_usaha TEXT,
    alamat_usaha TEXT,
    kegiatan_usaha TEXT,
    skala_usaha TEXT,
    sumber_data TEXT,
    kode_wilayah TEXT,
    kdprov TEXT NOT NULL,
    kdkab TEXT NOT NULL,
    kdkec TEXT NOT NULL,
    kddesa TEXT NOT NULL,
    nmprov TEXT NOT NULL,
    nmkab TEXT NOT NULL,
    nmkec TEXT NOT NULL,
    nmdesa TEXT NOT NULL,
    latitude NUMERIC,
    longitude NUMERIC,
    latlong_status TEXT,
    gcs_result TEXT,
    status_gc TEXT,
    status_perusahaan TEXT,
    gc_username TEXT,
    latitude_gc NUMERIC,
    longitude_gc NUMERIC,
    latlong_status_gc TEXT,
    history_ref_profiling_id TEXT,
    perusahaan_id TEXT,
    captured_at TIMESTAMP,
    batch_start TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes for fast filtering by region codes
CREATE INDEX IF NOT EXISTS idx_sbr_data_kdprov ON sbr_data(kdprov);
CREATE INDEX IF NOT EXISTS idx_sbr_data_kdkab ON sbr_data(kdprov, kdkab);
CREATE INDEX IF NOT EXISTS idx_sbr_data_kdkec ON sbr_data(kdprov, kdkab, kdkec);
CREATE INDEX IF NOT EXISTS idx_sbr_data_kddesa ON sbr_data(kdprov, kdkab, kdkec, kddesa);
CREATE INDEX IF NOT EXISTS idx_sbr_data_coords ON sbr_data(latitude, longitude);

-- Enable Row Level Security (RLS)
ALTER TABLE sbr_data ENABLE ROW LEVEL SECURITY;

-- Create RLS policy: allow anon users to read all rows
CREATE POLICY IF NOT EXISTS sbr_data_read ON sbr_data
    FOR SELECT
    USING (true);

-- Grant SELECT permission to anon and authenticated roles
GRANT SELECT ON sbr_data TO anon;
GRANT SELECT ON sbr_data TO authenticated;
