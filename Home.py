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
st.set_page_config(page_title="SBR Mapper", layout="wide")

# Global CSS — green Run button, full-width buttons, footer
st.markdown(
    """
    <style>
    /* Full-width for all primary buttons */
    div[data-testid="stButton"] > button {
        width: 100%;
    }
    /* Green colour for the Run Spatial Analysis button */
    div[data-testid="stButton"][id="run_btn_container"] > button,
    button[kind="primary"]#run_spatial_btn {
        background-color: #27ae60 !important;
        border-color: #27ae60 !important;
        color: #ffffff !important;
    }
    /* Target by key — Streamlit wraps button in a div whose child has data-testid */
    div:has(> button[kind="primary"]) button[kind="primary"].st-key-run_spatial_btn {
        background-color: #27ae60 !important;
        border-color: #27ae60 !important;
    }
    /* Footer */
    .sbr-footer {
        margin-top: 60px;
        padding: 28px 0 0 0;
        border-top: 1px solid rgba(255,255,255,0.12);
        text-align: center;
    }
    .sbr-footer-copy {
        font-size: 0.85rem;
        color: rgba(255,255,255,0.55);
        margin-bottom: 14px;
    }
    .sbr-footer-banner {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 20px;
        padding: 6px 16px;
        font-size: 0.78rem;
        color: rgba(255,255,255,0.6);
        text-decoration: none;
    }
    .sbr-footer-banner:hover {
        background: rgba(255,255,255,0.1);
        color: rgba(255,255,255,0.9);
    }
    .sbr-footer-banner svg {
        flex-shrink: 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div style="margin-bottom: 4px;">
        <span style="font-size:2rem; font-weight:700; letter-spacing:-0.5px;">🗺️ SBR Mapper</span>
    </div>
    <div style="font-size:1rem; color:rgba(255,255,255,0.55); margin-bottom: 20px;">
        Memetakan usaha-usaha se-Kalimantan Selatan
    </div>
    """,
    unsafe_allow_html=True,
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


def _best_coord_col(cols: list[str], kind: str) -> int:
    """
    Return the list index of the best coordinate column for *kind*
    ('lon' or 'lat'), preferring _gc suffix variants.

    Priority for lon: longitude_gc → longitude → lon → index 0
    Priority for lat: latitude_gc  → latitude  → lat → index 1
    """
    cols_lower = [c.lower() for c in cols]
    if kind == "lon":
        candidates = ["longitude_gc", "longitude", "lon"]
        fallback = 0
    else:
        candidates = ["latitude_gc", "latitude", "lat"]
        fallback = min(1, len(cols) - 1)
    for c in candidates:
        if c in cols_lower:
            return cols_lower.index(c)
    return fallback


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
            "empty_count":      int(empty_mask.sum()),
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

    geometry   = [Point(xy) for xy in zip(df_valid[x_col], df_valid[y_col])]
    gdf_points = gpd.GeoDataFrame(df_valid, geometry=geometry, crs="EPSG:4326")

    union = gdf_boundary.unary_union
    gdf_points["location_status"] = (
        gdf_points.geometry.within(union).map({True: "Inside", False: "Outside"})
    )

    return {"gdf_points": gdf_points, "gdf_polygon": gdf_boundary}


def _make_popup(row, status: str) -> str:
    """
    Build an HTML popup for a map marker showing:
      - nama_usaha  (bold header, if present)
      - gc_username (if present)
      - kegiatan_usaha (if present)
      - location status
    Falls back gracefully when columns are absent.
    """
    lines = []

    # Business name — bold header
    nama = row.get("nama_usaha") if hasattr(row, "get") else (
        row["nama_usaha"] if "nama_usaha" in row.index else None
    )
    if nama is not None and pd.notna(nama) and str(nama).strip():
        lines.append(f"<b>{nama}</b>")

    # GC username
    gc_user = None
    if "gc_username" in row.index:
        gc_user = row["gc_username"]
    if gc_user is not None and pd.notna(gc_user) and str(gc_user).strip():
        lines.append(f"👤 {gc_user}")

    # Business activity
    kegiatan = None
    if "kegiatan_usaha" in row.index:
        kegiatan = row["kegiatan_usaha"]
    if kegiatan is not None and pd.notna(kegiatan) and str(kegiatan).strip():
        lines.append(f"🏭 {kegiatan}")

    # Location status — always shown
    color_tag = "#27ae60" if status == "Inside" else "#e74c3c"
    lines.append(f"<span style='color:{color_tag};font-weight:600;'>{status}</span>")

    return "<br>".join(lines)


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _section(title: str, color_left: str):
    """Render a styled section header div (dark-theme safe, opening tag only)."""
    st.markdown(
        f"""<div style="border-left: 6px solid {color_left};
                       padding: 18px 20px 18px 24px;
                       border-radius: 8px;
                       margin: 12px 0 16px 0;
                       background: rgba(255,255,255,0.04);
                       box-shadow: 0 2px 8px rgba(0,0,0,0.25);">
            <h3 style="margin-top: 0; font-weight: 600;">{title}</h3>""",
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
        "kdprov": "Prov",
        "kdkab":  "Kab",
        "kdkec":  "Kec",
        "kddesa": "Desa",
    }
    parts = [f"{lbl}: {sel[k]}" for k, lbl in level_names.items() if sel[k]]
    return " › ".join(parts) if parts else "—"


# ---------------------------------------------------------------------------
# Streamlit cached file loaders (keyed on bytes so cache survives reruns)
# ---------------------------------------------------------------------------

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
for _key in ("validation_results", "spatial_results", "db_df", "db_x_col", "db_y_col"):
    if _key not in st.session_state:
        st.session_state[_key] = None


# ===========================================================================
# STEP 1 | gap | STEP 2  —  side by side  (55% | 5% | 40%)
# ===========================================================================
col_step1, col_gap, col_step2 = st.columns([55, 5, 40])

df    = None
x_col = None
y_col = None
sep   = ","

# ---------------------------------------------------------------------------
# LEFT — Step 1: Select Data Source
# ---------------------------------------------------------------------------
with col_step1:
    _section("📂 Step 1: Select Data Source", "#667eea")

    data_source = st.radio(
        "How would you like to provide coordinate data?",
        options=["Upload File", "Fetch from Database"],
        horizontal=True,
        key="data_source_radio",
    )

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
                        ","  if sep_opt == "Comma (,)"     else
                        ";"  if sep_opt == "Semicolon (;)" else
                        "\t" if sep_opt == "Tab (\\t)"     else
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

                # Column selectors — prefer _gc suffix variants
                cols = df.columns.tolist()
                x_idx = _best_coord_col(cols, "lon")
                y_idx = _best_coord_col(cols, "lat")
                c1, c2 = st.columns(2)
                with c1:
                    x_col = st.selectbox(
                        "Longitude column (X)", cols, index=x_idx, key="upload_x"
                    )
                with c2:
                    y_col = st.selectbox(
                        "Latitude column (Y)", cols, index=y_idx, key="upload_y"
                    )

            except Exception as e:
                st.error(f"Error reading file: {e}")

    else:
        # Database fetch mode
        st.markdown("**Filter data by region:**")
        data_sel = render_region_selector("data")

        if data_sel["kdprov"]:
            if st.button("📥 Fetch Data from Database", type="primary",
                         use_container_width=True, key="fetch_btn"):
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
                        # Prefer GC coordinates; fall back to raw coordinates
                        cols = fetched.columns.tolist()
                        xc = cols[_best_coord_col(cols, "lon")]
                        yc = cols[_best_coord_col(cols, "lat")]
                        st.session_state.db_df    = fetched
                        st.session_state.db_x_col = xc
                        st.session_state.db_y_col = yc
                        st.success(
                            f"✅ Fetched **{len(fetched):,}** rows "
                            f"(coords: {xc} / {yc})"
                        )

        # Persist fetched data across reruns
        if st.session_state.db_df is not None:
            df    = st.session_state.db_df
            x_col = st.session_state.db_x_col
            y_col = st.session_state.db_y_col

    # Compact data preview
    if df is not None:
        with st.expander("📊 Data Preview", expanded=False):
            ca, cb = st.columns(2)
            ca.metric("Rows", f"{len(df):,}")
            cb.metric("Columns", len(df.columns))
            st.dataframe(df.head(), width="stretch")

    _section_end()


# ---------------------------------------------------------------------------
# GAP column — intentionally empty
# ---------------------------------------------------------------------------
with col_gap:
    pass


# ---------------------------------------------------------------------------
# RIGHT — Step 2: Region Boundary + Run Analysis
# ---------------------------------------------------------------------------
with col_step2:
    _section("🗺️ Step 2: Select Region Boundary", "#00c9a7")

    if df is None or not x_col or not y_col:
        st.info("Load data in Step 1 first.")
        boundary_sel = {"kdprov": None, "kdkab": None, "kdkec": None, "kddesa": None}
    else:
        st.markdown(
            "Choose the administrative boundary. "
            "Stop at any level — child polygons dissolve automatically."
        )
        boundary_sel = render_region_selector("boundary")
        if boundary_sel["kdprov"]:
            st.info(f"Selected: **{region_label(boundary_sel)}**")

        # Run Spatial Analysis button lives here in Step 2
        if boundary_sel["kdprov"]:
            st.markdown(
                """<style>
                div[data-testid="stButton"]:has(button.st-key-run_spatial_btn) button {
                    background-color: #27ae60 !important;
                    border-color: #1e8449 !important;
                    color: #ffffff !important;
                }
                </style>""",
                unsafe_allow_html=True,
            )
            run_clicked = st.button(
                "🚀 Run Spatial Analysis",
                type="primary",
                use_container_width=True,
                key="run_spatial_btn",
            )

            if run_clicked:
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
                            pts     = spatial["gdf_points"]
                            inside  = int((pts["location_status"] == "Inside").sum())
                            outside = int((pts["location_status"] == "Outside").sum())
                            st.success(
                                f"✅ Done — {inside:,} inside | {outside:,} outside"
                            )
                        else:
                            st.warning("No valid coordinates to analyse spatially.")

    _section_end()


# ===========================================================================
# STEP 3 — RESULT
# ===========================================================================
if st.session_state.validation_results:
    st.markdown("---")
    _section("📊 Step 3: Result", "#f39c12")

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
                tiles="CartoDB dark_matter",
            )
            folium.GeoJson(
                gdf_polygon,
                style_function=lambda _: {
                    "fillColor": "#3498db",
                    "color": "#5dade2",
                    "weight": 2,
                    "fillOpacity": 0.08,
                },
            ).add_to(m)

            n          = len(gdf_points)
            SAMPLE_MAX = 5_000

            if n < 500:
                # All individual markers
                for _, row in gdf_points.iterrows():
                    status = row["location_status"]
                    color  = "#2ecc71" if status == "Inside" else "#e74c3c"
                    folium.CircleMarker(
                        location=[row[yc], row[xc]],
                        radius=5, color=color, fill=True,
                        fill_color=color, fill_opacity=0.85,
                        popup=folium.Popup(_make_popup(row, status), max_width=280),
                    ).add_to(m)
                st.success(f"✅ {n:,} individual markers")

            elif n < 10_000:
                # All points, separate Inside / Outside clusters
                st.info(f"📍 {n:,} points with clustering")
                cl_in  = MarkerCluster(name="Inside").add_to(m)
                cl_out = MarkerCluster(name="Outside").add_to(m)
                for _, row in gdf_points.iterrows():
                    status = row["location_status"]
                    color  = "#2ecc71" if status == "Inside" else "#e74c3c"
                    target = cl_in if status == "Inside" else cl_out
                    folium.CircleMarker(
                        location=[row[yc], row[xc]],
                        radius=5, color=color, fill=True,
                        fill_color=color, fill_opacity=0.85,
                        popup=folium.Popup(_make_popup(row, status), max_width=280),
                    ).add_to(target)
                folium.LayerControl().add_to(m)

            else:
                # Large dataset: all Outside first, then fill with sampled Inside
                df_outside = gdf_points[gdf_points["location_status"] == "Outside"]
                df_inside  = gdf_points[gdf_points["location_status"] == "Inside"]
                n_outside  = len(df_outside)
                inside_budget = max(0, SAMPLE_MAX - n_outside)

                if len(df_inside) > inside_budget:
                    df_inside_show = df_inside.sample(n=inside_budget, random_state=42)
                else:
                    df_inside_show = df_inside

                display     = pd.concat([df_outside, df_inside_show])
                total_shown = len(display)

                if len(df_inside) > inside_budget:
                    st.warning(
                        f"⚠️ {n:,} total points — showing all {n_outside:,} outside "
                        f"+ {len(df_inside_show):,} sampled inside "
                        f"({total_shown:,} markers total)."
                    )
                else:
                    st.info(f"📍 {total_shown:,} points with clustering")

                cl_in  = MarkerCluster(name="Inside").add_to(m)
                cl_out = MarkerCluster(name="Outside").add_to(m)
                for _, row in display.iterrows():
                    status = row["location_status"]
                    color  = "#2ecc71" if status == "Inside" else "#e74c3c"
                    target = cl_in if status == "Inside" else cl_out
                    folium.CircleMarker(
                        location=[row[yc], row[xc]],
                        radius=4, color=color, fill=True,
                        fill_color=color, fill_opacity=0.8,
                        popup=folium.Popup(_make_popup(row, status), max_width=280),
                    ).add_to(target)
                folium.LayerControl().add_to(m)

            # returned_objects=[] prevents reruns on pan/zoom
            st_folium(m, width=None, height=520, key="main_map", returned_objects=[])
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
            st.dataframe(show, width="stretch")
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
            st.dataframe(outside, width="stretch")
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
            st.dataframe(df_zero, width="stretch")
            if not df_zero.empty:
                st.download_button(
                    "⬇️ Download Zero Rows",
                    df_zero.to_csv(index=False).encode(),
                    "zero_coordinates.csv", "text/csv",
                )

        # ---- Empty ----
        with tab5:
            st.info(f"{len(df_empty):,} rows with empty/null coordinates")
            st.dataframe(df_empty, width="stretch")
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
            st.dataframe(df_invalid, width="stretch")
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
            c1.metric("Valid",       f"{len(gdf_points):,}")
            c2.metric("✅ Inside",   f"{inside_n:,}")
            c3.metric("🔴 Outside",  f"{outside_n:,}")
            c4.metric("Zero (0,0)",  f"{len(df_zero):,}")
            c5.metric("Empty/Null",  f"{len(df_empty):,}")
            c6.metric("Invalid",     f"{len(df_invalid):,}")

    # ----- validation-only mode (no spatial results yet) -----
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
            st.dataframe(df_valid, width="stretch")
            if not df_valid.empty:
                st.download_button(
                    "⬇️ Download Valid Data",
                    df_valid.to_csv(index=False).encode(),
                    "valid_coordinates.csv", "text/csv",
                )

        with tab4:
            st.warning(f"{len(df_zero):,} rows with (0, 0) coordinates")
            st.dataframe(df_zero, width="stretch")
            if not df_zero.empty:
                st.download_button(
                    "⬇️ Download Zero Rows",
                    df_zero.to_csv(index=False).encode(),
                    "zero_coordinates.csv", "text/csv",
                )

        with tab5:
            st.info(f"{len(df_empty):,} rows with empty/null coordinates")
            st.dataframe(df_empty, width="stretch")
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
            st.dataframe(df_invalid, width="stretch")
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

    _section_end()


# ===========================================================================
# FOOTER
# ===========================================================================
st.markdown(
    """
    <div class="sbr-footer">
        <div class="sbr-footer-copy">
            Copyright &copy; 2026 MPP TI BPS Provinsi Kalimantan Selatan
        </div>
        <a class="sbr-footer-banner"
           href="https://github.com/Sansadewa"
           target="_blank" rel="noopener noreferrer">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"
                 xmlns="http://www.w3.org/2000/svg">
                <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385
                         .6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235
                         -3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41
                         -1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015
                         1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99
                         .105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46
                         -5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53
                         .12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405
                         3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23
                         .66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225
                         0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81
                         2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57
                         A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/>
            </svg>
            github.com/Sansadewa
        </a>
    </div>
    """,
    unsafe_allow_html=True,
)
