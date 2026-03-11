# AGENTS.md - Guidelines for Agentic Code Work

## Project Overview
Python/Streamlit application for validating geographic coordinates in CSV/Excel files
and running spatial inside/outside analysis against Indonesian administrative boundaries
stored in Supabase PostGIS.

**Key Technologies:** Python 3, Streamlit, pandas, geopandas, folium, Supabase (PostGIS)

---

## Project Structure

```
GeoJson-Point-Filter/
├── Home.py                      # Main Streamlit app
├── supabase_client.py           # All Supabase query functions
├── validate_coordinates.py      # CLI validator (file-based, no Supabase)
├── requirements.txt
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml             # Supabase credentials (gitignored — create locally)
├── scripts/
│   ├── setup_rpc.sql            # Run once in Supabase SQL Editor
│   └── import_boundaries.py     # Run once to load GeoJSON -> desa_boundaries table
└── polygons/                    # Gitignored — place per-kabupaten GeoJSON files here
```

---

## Build & Run Commands

### Environment Setup
```bash
python -m venv venv
source venv/bin/activate          # Linux/Mac
pip install -r requirements.txt
```

### Run the App
```bash
streamlit run Home.py
```

### CLI Validator (no Supabase needed)
```bash
python validate_coordinates.py data.csv -x longitude -y latitude
python validate_coordinates.py data.csv -x lon -y lat --list-columns
python validate_coordinates.py data.csv -x lon -y lat -g boundary.geojson -o ./output
```

### Import Boundary Data (one-time setup)
```bash
# Dry run first to verify column mapping
python scripts/import_boundaries.py ./polygons/ --dry-run

# Real import
python scripts/import_boundaries.py ./polygons/
```

### Testing
No formal test framework. Manual testing:
- Upload a small CSV with known valid/invalid/zero/null coordinates
- Fetch from Supabase and pick a narrow region (single kecamatan)
- Confirm map shows correct inside/outside coloring

---

## Supabase Setup

### Credentials — `.streamlit/secrets.toml` (never commit this file)
```toml
[supabase]
url = "https://your-project.supabase.co"
key = "your-anon-key"
```

### Required Database Objects
1. **PostGIS extension** — `CREATE EXTENSION IF NOT EXISTS postgis;`
2. **`desa_boundaries` table** — desa polygons with parent codes:
   ```sql
   CREATE TABLE desa_boundaries (
       id      BIGSERIAL PRIMARY KEY,
       kdprov  TEXT NOT NULL, nmprov TEXT NOT NULL,
       kdkab   TEXT NOT NULL, nmkab  TEXT NOT NULL,
       kdkec   TEXT NOT NULL, nmkec  TEXT NOT NULL,
       kddesa  TEXT NOT NULL, nmdesa TEXT NOT NULL,
       geom    GEOMETRY(MultiPolygon, 4326) NOT NULL
   );
   CREATE INDEX ON desa_boundaries (kdprov);
   CREATE INDEX ON desa_boundaries (kdprov, kdkab);
   CREATE INDEX ON desa_boundaries (kdprov, kdkab, kdkec);
   CREATE INDEX ON desa_boundaries USING GIST (geom);
   ```
3. **RPC functions** — run `scripts/setup_rpc.sql` in the Supabase SQL Editor:
   - `get_regions(p_level, p_kdprov, p_kdkab, p_kdkec)` — cascading dropdown data
   - `get_boundary_geojson(p_kdprov, p_kdkab, p_kdkec, p_kddesa)` — dissolved boundary
4. **`sbr_data` table** — coordinate data with columns including:
   `latitude`, `longitude`, `kdprov`, `kdkab`, `kdkec`, `kddesa` (and more)
5. **PostgREST row limit** — increase beyond 1 000 in Supabase API settings

---

## Application Flow

```
Step 1 — Data Source
  [Radio] Upload File | Fetch from Supabase
    Upload: CSV/Excel uploader → column selector (x_col, y_col)
    Supabase: Cascading dropdown (prov→kab→kec→desa) → Fetch button
              x_col = "longitude", y_col = "latitude" (fixed)

Step 2 — Region Boundary  (visible after data is loaded)
  Cascading dropdown (prov→kab→kec→desa) from desa_boundaries
  User can stop at any level; child polygons are dissolved via ST_Union

Step 3 — Process  (visible after boundary is selected)
  Single "Run Spatial Analysis" button:
    1. run_validation(df, x_col, y_col)
    2. fetch_boundary(...)  → GeoDataFrame
    3. run_spatial_analysis(df_valid, x_col, y_col, gdf_boundary)
    → stores results in st.session_state

Results Tabs:
  Spatial mode:  Map | All Valid | Outside | Zero | Empty | Invalid | Summary
  Validation only: Valid | Zero | Empty | Invalid | Summary
```

---

## Code Style Guidelines

### Imports
- Standard library first (`sys`, `pathlib`, `io`)
- Third-party next (`pandas`, `geopandas`, `streamlit`, `folium`, `shapely`, `numpy`)
- Local modules last (`from supabase_client import ...`)
- Alphabetical within each group

### Naming Conventions
- `snake_case` for variables and functions
- `PascalCase` for classes (none currently)
- DataFrame variables prefixed with `df_` (e.g. `df_valid`, `df_zero`)
- GeoDataFrame variables prefixed with `gdf_`
- Column name variables: `x_col` (longitude), `y_col` (latitude)
- Region code variables: `kdprov`, `kdkab`, `kdkec`, `kddesa`
- Region name variables: `nmprov`, `nmkab`, `nmkec`, `nmdesa`

### Error Handling
- Wrap all Supabase calls in `try/except`; surface errors with `st.error()`
- Use `sys.exit(1)` for fatal errors in CLI scripts
- Check for empty DataFrames before operating: `if not df.empty:`
- Use `pd.isna()` to check for missing values (never `== None`)
- Use `np.nan` for missing numeric coordinate values

### Type Handling
- Load uploaded files with `dtype=str` for maximum flexibility
- Clean coordinates with `clean_coord()` before any numeric operations
- Convert to float with `try/except`, fallback to `np.nan`

### Coordinate Validation Flow
```
1. Load as strings (dtype=str)
2. clean_coord(): strip → replace ',' with '.' → float or np.nan
3. Categorise: empty (isna) → zero (0,0) → valid range → invalid
4. Create df_valid, df_zero, df_empty, df_invalid
5. Annotate df_invalid with _validation_issue column
```

### Streamlit Patterns
- `@st.cache_resource` for the Supabase client (one instance per session)
- `@st.cache_data(ttl=300)` for data fetches (5-minute TTL)
- `@st.cache_data` (no TTL) for file loading (keyed on bytes)
- `st.session_state` for results that must survive reruns:
  `validation_results`, `spatial_results`, `supabase_df`, `supabase_x_col`, `supabase_y_col`
- Use unique `key=` strings on every widget to avoid Streamlit conflicts
- Use `_section()` / `_section_end()` helpers for styled section divs

### Performance Considerations
- Cache all Supabase calls; never re-query on every rerun
- Map rendering thresholds: <500 individual markers, <10 000 clustered, else sample 5 000
- Use `MarkerCluster` for medium datasets with separate inside/outside clusters
- Fetch only required rows from Supabase (server-side filtering via `.eq()`)

### supabase_client.py conventions
- All public functions are module-level and independently cacheable
- Functions never call `st.stop()` — they return empty results and let the caller handle it
- `fetch_regions` always returns a `list[dict]` (never None)
- `fetch_boundary` returns `GeoDataFrame | None`
- `fetch_sbr_data` returns `pd.DataFrame` (empty on error)

---

## Common Tasks

### Add a new result tab
1. Add tab label in both the spatial-mode and validation-only `st.tabs()` calls
2. Write the `with tab_n:` block with `st.dataframe()` + `st.download_button()`
3. Update the Summary tab metrics

### Add a new validation category
1. Create mask in `run_validation()` in `Home.py`
2. Add the corresponding `df_category` slice
3. Return it in the dict and add session state handling
4. Add tab + download button in the Results section

### Change the Supabase boundary table structure
1. Update `scripts/setup_rpc.sql` RPC functions
2. Update column names in `supabase_client.py` `fetch_regions` / `fetch_boundary`
3. Update `scripts/import_boundaries.py` `REQUIRED_PROPS` list
4. Re-run the SQL in Supabase and re-import data

---

## Important Notes

- **GeoJSON must be EPSG:4326** (WGS84). The import script re-projects automatically.
- **GeoJSON feature properties** must include: `kdprov`, `kdkab`, `kdkec`, `kddesa`,
  `nmprov`, `nmkab`, `nmkec`, `nmdesa`. Extra properties are ignored.
- **`secrets.toml` is gitignored** — every developer must create it locally.
- **`polygons/` is gitignored** — place your per-kabupaten GeoJSON files there before importing.
- **Streamlit reruns on every widget interaction** — all mutable state must live in
  `st.session_state`, not local variables.
