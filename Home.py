import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from io import BytesIO, StringIO
from streamlit_folium import st_folium
from shapely.geometry import Point
import numpy as np
from folium.plugins import MarkerCluster

from supabase_client import fetch_regions, fetch_boundary, fetch_sbr_data

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Geo Spatial Filter", layout="wide")

st.title("📍 GeoJSON vs. CSV Point Analyzer")
st.markdown(
    "Validate coordinate data and run spatial inside/outside analysis against "
    "an Indonesian administrative boundary."
)


# ---------------------------------------------------------------------------
# Pure helper functions (no Streamlit I/O)
# ---------------------------------------------------------------------------

def clean_coord(val):
    """Convert a raw cell value to float, returning np.nan on failure."""
    if pd.isna(val):
        return np.nan
    val = str(val).strip().replace(",", ".")
    try:
        return float(val)
    except Exception:
        return np.nan


def run_validation(df: pd.DataFrame, x_col: str, y_col: str) -> dict:
    """
    Categorise every row of *df* by coordinate quality.

    Returns a dict with keys:
        df_valid, df_invalid, df_zero, df_empty,
        df_raw_len, x_col, y_col, diagnostics
    """
    df_clean = df.copy()
    df_clean[x_col] = df_clean[x_col].apply(clean_coord)
    df_clean[y_col] = df_clean[y_col].apply(clean_coord)

    empty_mask = df_clean[x_col].isna() | df_clean[y_col].isna()
    zero_mask  = (df_clean[x_col] == 0) & (df_clean[y_col] == 0)
    range_mask = (
        df_clean[x_col].between(-180, 180) &
        df_clean[y_col].between(-90,  90)
    )
    valid_mask = range_mask & ~zero_mask & ~empty_mask

    df_valid   = df_clean[valid_mask].copy()
    df_zero    = df[zero_mask].copy()
    df_empty   = df[empty_mask].copy()
    df_invalid = df[~(valid_mask | zero_mask | empty_mask)].copy()

    # Annotate invalid rows with a reason
    if not df_invalid.empty:
        df_invalid = df_invalid.copy()
        df_invalid["_validation_issue"] = ""
        for idx in df_invalid.index:
            xv = df_clean.loc[idx, x_col]
            yv = df_clean.loc[idx, y_col]
            if pd.isna(xv) or pd.isna(yv):
                reason = "Empty/Null value"
            elif xv < -180 or xv > 180:
                reason = f"Lon out of range ({xv})"
            elif yv < -90 or yv > 90:
                reason = f"Lat out of range ({yv})"
            else:
                reason = "Cannot convert to number"
            df_invalid.loc[idx, "_validation_issue"] = reason

    return {
        "df_valid":   df_valid,
        "df_invalid": df_invalid,
        "df_zero":    df_zero,
        "df_empty":   df_empty,
        "df_raw_len": len(df),
        "x_col":      x_col,
        "y_col":      y_col,
        "diagnostics": {
            "empty_count":     int(empty_mask.sum()),
            "out_of_range_lon": int(((df_clean[x_col] < -180) | (df_clean[x_col] > 180)).sum()),
            "out_of_range_lat": int(((df_clean[y_col] < -90)  | (df_clean[y_col] > 90)).sum()),
        },
    }


def run_spatial_analysis(df_valid: pd.DataFrame, x_col: str, y_col: str,
                         gdf_boundary: gpd.GeoDataFrame) -> dict | None:
    """
    Test each valid point for containment within *gdf_boundary*.

    Returns a dict with gdf_points and gdf_polygon, or None when
    df_valid is empty.
    """
    if df_valid.empty:
        return None

    geometry  = [Point(xy) for xy in zip(df_valid[x_col], df_valid[y_col])]
    gdf_points = gpd.GeoDataFrame(df_valid, geometry=geometry, crs="EPSG:4326")

    union = gdf_boundary.unary_union
    gdf_points["location_status"] = (
        gdf_points.geometry.within(union).map({True: "Inside", False: "Outside"})
    )

    return {"gdf_points": gdf_points, "gdf_polygon": gdf_boundary}


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _section(title: str, color_left: str, color_bg: str):
    """Render a styled section header div (opening tag only)."""
    st.markdown(
        f"""<div style="background: linear-gradient(to right, {color_bg} 0%, #fafafa 100%);
                       border-left: 10px solid {color_left};
                       padding: 25px 25px 25px 30px;
                       border-radius: 10px;
                       margin: 20px 0;
                       box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
            <h3 style="color: #2c3e50; margin-top: 0; font-weight: 600;">{title}</h3>""",
        unsafe_allow_html=True,
    )


def _section_end():
    st.markdown("</div>", unsafe_allow_html=True)


def render_region_selector(key_prefix: str) -> dict:
    """
    Render cascading Provinsi → Kabupaten → Kecamatan → Desa dropdowns.

    The user can stop at any level; any unselected levels are returned
    as None so the boundary query dissolves all child polygons.

    Args:
        key_prefix: Unique prefix for Streamlit widget keys.

    Returns:
        dict with keys kdprov, kdkab, kdkec, kddesa (each str or None).
    """
    sel = {"kdprov": None, "kdkab": None, "kdkec": None, "kddesa": None}

    # --- Provinsi ---
    prov_data = fetch_regions("provinsi")
    if not prov_data:
        st.warning("No region data found in `desa_boundaries`. Run the import script first.")
        return sel

    prov_map = {r["nama"]: r["kode"] for r in prov_data}
    prov_choice = st.selectbox(
        "Provinsi",
        options=["— Select Provinsi —"] + list(prov_map),
        key=f"{key_prefix}_prov",
    )
    if prov_choice == "— Select Provinsi —":
        return sel
    sel["kdprov"] = prov_map[prov_choice]

    # --- Kabupaten ---
    kab_data = fetch_regions("kabupaten", kdprov=sel["kdprov"])
    kab_map  = {r["nama"]: r["kode"] for r in kab_data}
    kab_choice = st.selectbox(
        "Kabupaten/Kota",
        options=["— All (entire Provinsi) —"] + list(kab_map),
        key=f"{key_prefix}_kab",
    )
    if kab_choice == "— All (entire Provinsi) —":
        return sel
    sel["kdkab"] = kab_map[kab_choice]

    # --- Kecamatan ---
    kec_data = fetch_regions("kecamatan", kdprov=sel["kdprov"], kdkab=sel["kdkab"])
    kec_map  = {r["nama"]: r["kode"] for r in kec_data}
    kec_choice = st.selectbox(
        "Kecamatan",
        options=["— All (entire Kabupaten) —"] + list(kec_map),
        key=f"{key_prefix}_kec",
    )
    if kec_choice == "— All (entire Kabupaten) —":
        return sel
    sel["kdkec"] = kec_map[kec_choice]

    # --- Desa ---
    desa_data = fetch_regions("desa", kdprov=sel["kdprov"], kdkab=sel["kdkab"], kdkec=sel["kdkec"])
    desa_map  = {r["nama"]: r["kode"] for r in desa_data}
    desa_choice = st.selectbox(
        "Desa/Kelurahan",
        options=["— All (entire Kecamatan) —"] + list(desa_map),
        key=f"{key_prefix}_desa",
    )
    if desa_choice == "— All (entire Kecamatan) —":
        return sel
    sel["kddesa"] = desa_map[desa_choice]

    return sel


def region_label(sel: dict) -> str:
    """Return a human-readable breadcrumb for the selected region."""
    level_names = {
        "kdprov":  "Prov",
        "kdkab":   "Kab",
        "kdkec":   "Kec",
        "kddesa":  "Desa",
    }
    parts = [f"{lbl}: {sel[k]}" for k, lbl in level_names.items() if sel[k]]
    return " › ".join(parts) if parts else "—"


# ---------------------------------------------------------------------------
# Streamlit cached file loaders (keyed on bytes so cache survives reruns)
# ---------------------------------------------------------------------------

@st.cache_data
def _load_upload(file_bytes: bytes, file_name: str, separator: str) -> pd.DataFrame:
    ext = file_name.rsplit(".", 1)[-1].lower()
    if ext in ("xlsx", "xls"):
        return pd.read_excel(BytesIO(file_bytes), dtype=str)
    return pd.read_csv(StringIO(file_bytes.decode("utf-8")), sep=separator, dtype=str)


@st.cache_data
def _get_excel_sheets(file_bytes: bytes, file_name: str) -> list[str] | None:
    ext = file_name.rsplit(".", 1)[-1].lower()
    if ext in ("xlsx", "xls"):
        xf = pd.ExcelFile(BytesIO(file_bytes))
        return xf.sheet_names
    return None


@st.cache_data
def _load_upload_sheet(file_bytes: bytes, file_name: str, separator: str,
                       sheet_name: str | None) -> pd.DataFrame:
    ext = file_name.rsplit(".", 1)[-1].lower()
    if ext in ("xlsx", "xls"):
        return pd.read_excel(BytesIO(file_bytes), dtype=str, sheet_name=sheet_name)
    return pd.read_csv(StringIO(file_bytes.decode("utf-8")), sep=separator, dtype=str)


# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------
for key in ("validation_results", "spatial_results", "supabase_df",
            "supabase_x_col", "supabase_y_col"):
    if key not in st.session_state:
        st.session_state[key] = None


# ===========================================================================
# STEP 1 — DATA SOURCE
# ===========================================================================
_section("📂 Step 1: Select Data Source", "#667eea", "#f0ebff")

data_source = st.radio(
    "How would you like to provide coordinate data?",
    options=["Upload File", "Fetch from Supabase"],
    horizontal=True,
    key="data_source_radio",
)

df       = None
x_col    = None
y_col    = None
sep      = ","

if data_source == "Upload File":
    csv_file = st.file_uploader(
        "Upload CSV / Excel file", type=["csv", "txt", "xlsx", "xls"]
    )

    if csv_file is not None:
        ext = csv_file.name.rsplit(".", 1)[-1].lower()

        # CSV delimiter picker
        if ext not in ("xlsx", "xls"):
            with st.expander("🛠️ CSV Settings", expanded=False):
                sep_opt = st.selectbox(
                    "Column separator",
                    ["Comma (,)", "Semicolon (;)", "Tab (\\t)", "Pipe (|)", "Custom"],
                    key="sep_select",
                )
                sep = (
                    ","  if sep_opt == "Comma (,)"    else
                    ";"  if sep_opt == "Semicolon (;)" else
                    "\t" if sep_opt == "Tab (\\t)"    else
                    "|"  if sep_opt == "Pipe (|)"      else
                    st.text_input("Custom delimiter", value=",")
                )

        try:
            csv_file.seek(0)
            file_bytes = csv_file.read()

            # Sheet picker for multi-sheet Excel
            selected_sheet = None
            if ext in ("xlsx", "xls"):
                sheets = _get_excel_sheets(file_bytes, csv_file.name)
                if sheets and len(sheets) > 1:
                    st.info(f"📊 Excel has {len(sheets)} sheets")
                    selected_sheet = st.selectbox(
                        "Select sheet", sheets, key="sheet_select"
                    )
                elif sheets:
                    selected_sheet = sheets[0]

            df = _load_upload_sheet(file_bytes, csv_file.name, sep, selected_sheet)
            st.success(f"✅ Loaded **{len(df):,}** rows from {csv_file.name}")

            # Column selectors
            cols = df.columns.tolist()
            c1, c2 = st.columns(2)
            with c1:
                x_col = st.selectbox(
                    "Longitude column (X)", cols, index=0, key="upload_x"
                )
            with c2:
                y_col = st.selectbox(
                    "Latitude column (Y)",
                    cols,
                    index=min(1, len(cols) - 1),
                    key="upload_y",
                )

        except Exception as e:
            st.error(f"Error reading file: {e}")

else:
    # Supabase fetch mode
    st.markdown("**Filter data by region:**")
    data_sel = render_region_selector("data")

    if data_sel["kdprov"]:
        if st.button("📥 Fetch Data from Supabase", type="primary", key="fetch_btn"):
            with st.spinner("Fetching data…"):
                fetched = fetch_sbr_data(
                    kdprov=data_sel["kdprov"],
                    kdkab=data_sel["kdkab"],
                    kdkec=data_sel["kdkec"],
                    kddesa=data_sel["kddesa"],
                )
                if fetched.empty:
                    st.warning("No rows found for the selected region.")
                else:
                    st.session_state.supabase_df    = fetched
                    st.session_state.supabase_x_col = "longitude"
                    st.session_state.supabase_y_col = "latitude"
                    st.success(f"✅ Fetched **{len(fetched):,}** rows")

    # Persist fetched data across reruns
    if st.session_state.supabase_df is not None:
        df    = st.session_state.supabase_df
        x_col = st.session_state.supabase_x_col
        y_col = st.session_state.supabase_y_col

# Compact data preview
if df is not None:
    with st.expander("📊 Data Preview", expanded=False):
        ca, cb = st.columns(2)
        ca.metric("Rows", f"{len(df):,}")
        cb.metric("Columns", len(df.columns))
        st.dataframe(df.head(), use_container_width=True)

_section_end()


# ===========================================================================
# STEP 2 — REGION BOUNDARY
# ===========================================================================
if df is not None and x_col and y_col:
    _section("🗺️ Step 2: Select Region Boundary", "#00f2fe", "#e6f9ff")

    st.markdown(
        "Choose the administrative boundary to check your points against. "
        "Stop at any level — all child polygons will be dissolved automatically."
    )

    boundary_sel = render_region_selector("boundary")

    if boundary_sel["kdprov"]:
        st.info(f"Selected boundary: **{region_label(boundary_sel)}**")

    _section_end()


    # =======================================================================
    # STEP 3 — PROCESS
    # =======================================================================
    if boundary_sel["kdprov"]:
        _section("⚙️ Step 3: Process", "#f5576c", "#fff0f6")

        st.markdown(
            f"**Data:** {len(df):,} rows &nbsp;|&nbsp; "
            f"**Boundary:** {region_label(boundary_sel)}"
        )

        if st.button(
            "🚀 Run Spatial Analysis", type="primary",
            use_container_width=True, key="process_btn"
        ):
            with st.spinner("Validating coordinates and fetching boundary…"):

                # 1. Validate
                validation = run_validation(df, x_col, y_col)
                st.session_state.validation_results = validation

                v = validation
                st.info(
                    f"📊 Validation — "
                    f"✅ Valid: {len(v['df_valid']):,} | "
                    f"❌ Invalid: {len(v['df_invalid']):,} | "
                    f"0️⃣ Zero: {len(v['df_zero']):,} | "
                    f"📭 Empty: {len(v['df_empty']):,}"
                )

                # 2. Fetch boundary
                gdf_boundary = fetch_boundary(
                    kdprov=boundary_sel["kdprov"],
                    kdkab=boundary_sel["kdkab"],
                    kdkec=boundary_sel["kdkec"],
                    kddesa=boundary_sel["kddesa"],
                )

                if gdf_boundary is None or gdf_boundary.empty:
                    st.error("Could not load boundary for the selected region.")
                    st.session_state.spatial_results = None
                else:
                    # 3. Spatial analysis
                    spatial = run_spatial_analysis(
                        v["df_valid"], x_col, y_col, gdf_boundary
                    )
                    st.session_state.spatial_results = spatial

                    if spatial:
                        pts = spatial["gdf_points"]
                        inside  = int((pts["location_status"] == "Inside").sum())
                        outside = int((pts["location_status"] == "Outside").sum())
                        st.success(
                            f"✅ Done — {inside:,} inside | {outside:,} outside"
                        )
                    else:
                        st.warning("No valid coordinates to analyse spatially.")

        _section_end()


# ===========================================================================
# RESULTS
# ===========================================================================
if st.session_state.validation_results:
    st.markdown("---")
    st.markdown("### 📊 Results")

    val_res     = st.session_state.validation_results
    spatial_res = st.session_state.spatial_results

    df_valid   = val_res["df_valid"]
    df_invalid = val_res["df_invalid"]
    df_zero    = val_res["df_zero"]
    df_empty   = val_res["df_empty"]
    xc         = val_res["x_col"]
    yc         = val_res["y_col"]

    # ----- spatial mode -----
    if spatial_res:
        gdf_points  = spatial_res["gdf_points"]
        gdf_polygon = spatial_res["gdf_polygon"]

        tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
            "🗺️ Map",
            "✅ All Valid",
            "🔴 Outside Boundary",
            "0️⃣ Zero Coords",
            "📭 Empty/Null",
            "❌ Invalid",
            "📊 Summary",
        ])

        # ---- Map ----
        with tab1:
            center_lat = float(gdf_points[yc].mean())
            center_lon = float(gdf_points[xc].mean())
            m = folium.Map(
                location=[center_lat, center_lon],
                zoom_start=12,
                tiles="CartoDB positron",
            )
            folium.GeoJson(
                gdf_polygon,
                style_function=lambda _: {
                    "fillColor": "blue", "color": "blue", "fillOpacity": 0.1
                },
            ).add_to(m)

            n = len(gdf_points)
            if n < 500:
                for _, row in gdf_points.iterrows():
                    color = "#2ecc71" if row["location_status"] == "Inside" else "#e74c3c"
                    folium.CircleMarker(
                        location=[row[yc], row[xc]],
                        radius=4, color=color, fill=True,
                        fill_color=color, fill_opacity=0.8,
                        popup=f"Status: {row['location_status']}",
                    ).add_to(m)
                st.success(f"✅ {n} individual markers")

            elif n < 10_000:
                st.info(f"📍 {n} points with clustering")
                cl_in  = MarkerCluster(name="Inside").add_to(m)
                cl_out = MarkerCluster(name="Outside").add_to(m)
                for _, row in gdf_points.iterrows():
                    color  = "#2ecc71" if row["location_status"] == "Inside" else "#e74c3c"
                    target = cl_in if row["location_status"] == "Inside" else cl_out
                    folium.CircleMarker(
                        location=[row[yc], row[xc]],
                        radius=4, color=color, fill=True,
                        fill_color=color, fill_opacity=0.8,
                        popup=f"Status: {row['location_status']}",
                    ).add_to(target)
                folium.LayerControl().add_to(m)

            else:
                sample_n = 5_000
                st.warning(f"⚠️ {n} points — showing random sample of {sample_n}.")
                sampled = gdf_points.sample(n=sample_n, random_state=42)
                cl = MarkerCluster().add_to(m)
                for _, row in sampled.iterrows():
                    color = "#2ecc71" if row["location_status"] == "Inside" else "#e74c3c"
                    folium.CircleMarker(
                        location=[row[yc], row[xc]],
                        radius=3, color=color, fill=True,
                        fill_color=color, fill_opacity=0.7,
                        popup=f"Status: {row['location_status']}",
                    ).add_to(cl)

            st_folium(m, width=None, height=500, key="main_map")
            st.markdown(
                "**Legend:** 🟢 Inside boundary &nbsp; 🔴 Outside boundary "
                "&nbsp; 🔵 Region polygon"
            )

        # ---- All Valid ----
        with tab2:
            st.success(f"All valid coordinate data — {len(gdf_points):,} rows")
            all_valid = gdf_points.drop(columns="geometry").copy()
            filt = st.radio(
                "Filter:", ["All", "Inside Only", "Outside Only"], horizontal=True
            )
            show = (
                all_valid[all_valid["location_status"] == "Inside"]  if filt == "Inside Only"  else
                all_valid[all_valid["location_status"] == "Outside"] if filt == "Outside Only" else
                all_valid
            )
            st.dataframe(show, use_container_width=True)
            st.download_button(
                "⬇️ Download All Valid",
                all_valid.to_csv(index=False).encode(),
                "all_valid_points.csv", "text/csv",
            )

        # ---- Outside ----
        with tab3:
            outside = gdf_points[gdf_points["location_status"] == "Outside"].drop(columns="geometry")
            st.warning(f"{len(outside):,} valid points fall OUTSIDE the boundary")
            st.markdown(
                "These have valid coordinates but lie outside the selected region polygon."
            )
            st.dataframe(outside, use_container_width=True)
            if not outside.empty:
                st.download_button(
                    "⬇️ Download Outside Points",
                    outside.to_csv(index=False).encode(),
                    "outside_points.csv", "text/csv",
                )

        # ---- Zero ----
        with tab4:
            st.warning(f"{len(df_zero):,} rows with exactly (0, 0) coordinates")
            st.markdown("These often indicate missing GPS data.")
            st.dataframe(df_zero, use_container_width=True)
            if not df_zero.empty:
                st.download_button(
                    "⬇️ Download Zero Rows",
                    df_zero.to_csv(index=False).encode(),
                    "zero_coordinates.csv", "text/csv",
                )

        # ---- Empty ----
        with tab5:
            st.info(f"{len(df_empty):,} rows with empty/null coordinates")
            st.dataframe(df_empty, use_container_width=True)
            if not df_empty.empty:
                st.download_button(
                    "⬇️ Download Empty Rows",
                    df_empty.to_csv(index=False).encode(),
                    "empty_coordinates.csv", "text/csv",
                )

        # ---- Invalid ----
        with tab6:
            st.error(f"{len(df_invalid):,} rows with invalid coordinates")
            if "diagnostics" in val_res and not df_invalid.empty:
                diag = val_res["diagnostics"]
                d1, d2 = st.columns(2)
                d1.metric("Lon out of range", diag["out_of_range_lon"], help="Valid: −180 to 180")
                d2.metric("Lat out of range", diag["out_of_range_lat"], help="Valid: −90 to 90")
            st.dataframe(df_invalid, use_container_width=True)
            if not df_invalid.empty:
                st.download_button(
                    "⬇️ Download Invalid Rows",
                    df_invalid.to_csv(index=False).encode(),
                    "invalid_rows.csv", "text/csv",
                )

        # ---- Summary ----
        with tab7:
            st.metric("Total Rows", f"{val_res['df_raw_len']:,}")
            inside_n  = int((gdf_points["location_status"] == "Inside").sum())
            outside_n = int((gdf_points["location_status"] == "Outside").sum())
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("Valid",         f"{len(gdf_points):,}")
            c2.metric("✅ Inside",     f"{inside_n:,}")
            c3.metric("🔴 Outside",    f"{outside_n:,}")
            c4.metric("Zero (0,0)",    f"{len(df_zero):,}")
            c5.metric("Empty/Null",    f"{len(df_empty):,}")
            c6.metric("Invalid",       f"{len(df_invalid):,}")

    # ----- validation-only mode (boundary not yet run) -----
    else:
        tab2, tab4, tab5, tab6, tab7 = st.tabs([
            "✅ Valid Coordinates",
            "0️⃣ Zero Coords",
            "📭 Empty/Null",
            "❌ Invalid",
            "📊 Summary",
        ])

        with tab2:
            st.success(f"Valid coordinate data — {len(df_valid):,} rows")
            st.dataframe(df_valid, use_container_width=True)
            if not df_valid.empty:
                st.download_button(
                    "⬇️ Download Valid Data",
                    df_valid.to_csv(index=False).encode(),
                    "valid_coordinates.csv", "text/csv",
                )

        with tab4:
            st.warning(f"{len(df_zero):,} rows with (0, 0) coordinates")
            st.dataframe(df_zero, use_container_width=True)
            if not df_zero.empty:
                st.download_button(
                    "⬇️ Download Zero Rows",
                    df_zero.to_csv(index=False).encode(),
                    "zero_coordinates.csv", "text/csv",
                )

        with tab5:
            st.info(f"{len(df_empty):,} rows with empty/null coordinates")
            st.dataframe(df_empty, use_container_width=True)
            if not df_empty.empty:
                st.download_button(
                    "⬇️ Download Empty Rows",
                    df_empty.to_csv(index=False).encode(),
                    "empty_coordinates.csv", "text/csv",
                )

        with tab6:
            st.error(f"{len(df_invalid):,} rows with invalid coordinates")
            if "diagnostics" in val_res and not df_invalid.empty:
                diag = val_res["diagnostics"]
                st.markdown("### 🔍 Why is my data invalid?")
                d1, d2 = st.columns(2)
                d1.metric("Lon out of range", diag["out_of_range_lon"], help="Valid: −180 to 180")
                d2.metric("Lat out of range", diag["out_of_range_lat"], help="Valid: −90 to 90")
                st.markdown("""
                **Common causes:**
                - **Swapped columns** — Lat should be −90 to 90, Lon −180 to 180
                - **Wrong projection** — UTM / DMS not supported; must be decimal degrees
                - **Text values** — Non-numeric data in coordinate columns
                """)
            st.markdown("---")
            st.dataframe(df_invalid, use_container_width=True)
            if not df_invalid.empty:
                st.download_button(
                    "⬇️ Download Invalid Rows",
                    df_invalid.to_csv(index=False).encode(),
                    "invalid_rows.csv", "text/csv",
                )

        with tab7:
            st.metric("Total Rows", f"{val_res['df_raw_len']:,}")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("✅ Valid",       f"{len(df_valid):,}")
            c2.metric("0️⃣ Zero (0,0)", f"{len(df_zero):,}")
            c3.metric("📭 Empty/Null",  f"{len(df_empty):,}")
            c4.metric("❌ Invalid",     f"{len(df_invalid):,}")
