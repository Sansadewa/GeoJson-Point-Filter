#!/usr/bin/env python3
"""
Create the sbr_data table in Supabase.
This script runs the SQL to set up the table structure, indexes, and RLS policies.

Usage:
    python scripts/setup_sbr_data.py
"""

import sys
import re
from pathlib import Path

from supabase import create_client


def load_secrets():
    """Load Supabase credentials from .streamlit/secrets.toml."""
    secrets_path = Path(__file__).parent.parent / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        print(f"ERROR: {secrets_path} not found")
        sys.exit(1)
    text = secrets_path.read_text()
    url_m = re.search(r'url\s*=\s*"([^"]+)"', text)
    key_m = re.search(r'key\s*=\s*"([^"]+)"', text)
    if not url_m or not key_m:
        print("ERROR: secrets.toml must have [supabase] section with url and key")
        sys.exit(1)
    return url_m.group(1), key_m.group(1)


def main():
    print("=" * 60)
    print("Setting up sbr_data table in Supabase...")
    print("=" * 60)

    url, key = load_secrets()
    client = create_client(url, key)

    # SQL to create the table
    sql = """
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

    CREATE INDEX IF NOT EXISTS idx_sbr_data_kdprov ON sbr_data(kdprov);
    CREATE INDEX IF NOT EXISTS idx_sbr_data_kdkab ON sbr_data(kdprov, kdkab);
    CREATE INDEX IF NOT EXISTS idx_sbr_data_kdkec ON sbr_data(kdprov, kdkab, kdkec);
    CREATE INDEX IF NOT EXISTS idx_sbr_data_kddesa ON sbr_data(kdprov, kdkab, kdkec, kddesa);
    CREATE INDEX IF NOT EXISTS idx_sbr_data_coords ON sbr_data(latitude, longitude);

    ALTER TABLE sbr_data ENABLE ROW LEVEL SECURITY;

    CREATE POLICY IF NOT EXISTS sbr_data_read ON sbr_data
        FOR SELECT
        USING (true);

    GRANT SELECT ON sbr_data TO anon;
    GRANT SELECT ON sbr_data TO authenticated;
    """

    try:
        result = client.rpc("exec", {"sql": sql}).execute()
        print("❌ RPC 'exec' not available (expected - Supabase doesn't expose raw SQL execution)")
        print("\nINSTRUCTIONS:")
        print("  1. Go to: https://supabase.com/dashboard/project/[YOUR_PROJECT]/sql")
        print("  2. Click 'New Query'")
        print("  3. Paste the SQL from scripts/setup_sbr_data.sql")
        print("  4. Click 'Run'")
        print("  5. Verify the table exists in the Schema browser")
        sys.exit(1)
    except Exception as e:
        print(f"ℹ️  Note: {e}")
        print("\nSince Supabase doesn't expose direct SQL execution via the API,")
        print("you must run the SQL manually in the Supabase SQL Editor.")
        print("\nSTEPS:")
        print("  1. Go to your Supabase Dashboard")
        print("  2. Click 'SQL Editor' in the left sidebar")
        print("  3. Click 'New Query'")
        print("  4. Paste the contents of: scripts/setup_sbr_data.sql")
        print("  5. Click 'Run'")
        print("\nThe SQL creates:")
        print("  ✅ sbr_data table with all required columns")
        print("  ✅ Indexes for fast filtering by region codes")
        print("  ✅ Row Level Security (RLS) policy")
        print("  ✅ Permissions for anon/authenticated roles")


if __name__ == "__main__":
    main()
