import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from streamlit_folium import st_folium
from shapely.geometry import Point
import numpy as np

# Set page configuration
st.set_page_config(page_title="Geo Spatial Filter", layout="wide")

st.title("📍 GeoJSON vs. CSV Point Analyzer")

# --- Step 1: File Uploads ---
col1, col2 = st.columns(2)
with col1:
    geojson_file = st.file_uploader("1. Upload GeoJSON (Polygon)", type=['geojson', 'json'])
with col2:
    csv_file = st.file_uploader("2. Upload CSV (Points)", type=['csv', 'txt'])

# --- Step 1.5: CSV Delimiter Settings ---
sep = ","
if csv_file is not None:
    with st.expander("🛠️ CSV Settings (Click if columns look wrong)", expanded=False):
        sep_option = st.selectbox(
            "Select Column Separator",
            options=["Comma (,)", "Semicolon (;)", "Tab (\\t)", "Pipe (|)", "Custom"],
            index=0
        )
        if sep_option == "Comma (,)": sep = ","
        elif sep_option == "Semicolon (;)": sep = ";"
        elif sep_option == "Tab (\\t)": sep = "\t"
        elif sep_option == "Pipe (|)": sep = "|"
        else: sep = st.text_input("Enter Custom Delimiter", value=",")

# --- Session State ---
if 'results' not in st.session_state:
    st.session_state.results = None

# --- Step 2: Processing ---
if geojson_file is not None and csv_file is not None:
    
    # Load GeoJSON
    try:
        gdf_polygon = gpd.read_file(geojson_file)
        if gdf_polygon.crs is not None:
            gdf_polygon = gdf_polygon.to_crs(epsg=4326)
        else:
            gdf_polygon.set_crs(epsg=4326, inplace=True)
    except Exception as e:
        st.error(f"Error reading GeoJSON: {e}")
        st.stop()

    # Load CSV
    try:
        csv_file.seek(0)
        df = pd.read_csv(csv_file, sep=sep, dtype=str)
    except Exception as e:
        st.error(f"Error reading CSV: {e}")
        st.stop()

    # Column Selectors
    st.divider()
    st.subheader("⚙️ Configure Coordinates")
    columns = df.columns.tolist()
    
    c1, c2 = st.columns(2)
    with c1:
        x_col = st.selectbox("Select X Column (Longitude)", options=columns, index=0)
    with c2:
        y_col = st.selectbox("Select Y Column (Latitude)", options=columns, index=1 if len(columns) > 1 else 0)

    # --- Analysis Trigger ---
    if st.button("Run Analysis", type="primary"):
        with st.spinner("Cleaning data and calculating..."):
            
            # 1. Clean Data (Handle commas)
            df_clean = df.copy()
            def clean_coord(val):
                if pd.isna(val): return np.nan
                val = str(val).strip().replace(',', '.')
                try:
                    return float(val)
                except:
                    return np.nan

            df_clean[x_col] = df_clean[x_col].apply(clean_coord)
            df_clean[y_col] = df_clean[y_col].apply(clean_coord)

            # 2. Categorize Data
            # A. Zero Coordinates (0,0) - Often default sensor values
            zero_mask = (df_clean[x_col] == 0) & (df_clean[y_col] == 0)
            
            # B. Invalid Range or Non-Numeric (excluding zeros)
            # Valid range: Lon -180 to 180, Lat -90 to 90
            valid_range_mask = (
                (df_clean[x_col].between(-180, 180)) & 
                (df_clean[y_col].between(-90, 90))
            )
            # Valid is in range AND not zero AND not NaN
            valid_mask = valid_range_mask & (~zero_mask) & (df_clean[x_col].notna()) & (df_clean[y_col].notna())

            # Create DataFrames
            df_valid = df_clean[valid_mask].copy()
            df_zero = df[zero_mask].copy()      # Use original df to preserve formatting if needed
            df_invalid = df[~(valid_mask | zero_mask)].copy() # Everything else is invalid

            # 3. Spatial Join (Only on Valid Data)
            if not df_valid.empty:
                geometry = [Point(xy) for xy in zip(df_valid[x_col], df_valid[y_col])]
                gdf_points = gpd.GeoDataFrame(df_valid, geometry=geometry, crs="EPSG:4326")
                
                polygon_union = gdf_polygon.unary_union
                gdf_points['location_status'] = gdf_points.geometry.within(polygon_union).map({True: 'Inside', False: 'Outside'})
                
                # Save to Session State
                st.session_state.results = {
                    'gdf_points': gdf_points,
                    'df_invalid': df_invalid,
                    'df_zero': df_zero,
                    'df_raw_len': len(df),
                    'x_col': x_col,
                    'y_col': y_col
                }
            else:
                 st.session_state.results = {'error': "No valid data found (check if all your data is 0,0 or invalid)."}

    # --- Step 3: Render Results ---
    if st.session_state.results:
        res = st.session_state.results
        
        if 'error' in res:
            st.error(res['error'])
        else:
            gdf_points = res['gdf_points']
            df_invalid = res['df_invalid']
            df_zero = res['df_zero']
            x_col = res['x_col']
            y_col = res['y_col']

            # Tabs
            tab1, tab2, tab3, tab4 = st.tabs(["🗺️ Map & Valid", "0️⃣ Zero Coordinates", "❌ Invalid Data", "📊 Summary"])

            with tab1:
                # Map Preparation
                center_lat = gdf_points[y_col].mean()
                center_lon = gdf_points[x_col].mean()
                
                m = folium.Map(location=[center_lat, center_lon], zoom_start=12, tiles="CartoDB positron")
                folium.GeoJson(gdf_polygon, style_function=lambda x: {'fillColor': 'blue', 'color': 'blue', 'fillOpacity': 0.1}).add_to(m)

                # Markers
                if len(gdf_points) < 2000:
                    for idx, row in gdf_points.iterrows():
                        color = '#2ecc71' if row['location_status'] == 'Inside' else '#e74c3c'
                        folium.CircleMarker(
                            location=[row[y_col], row[x_col]], radius=4, color=color, fill=True, fill_color=color, fill_opacity=0.8,
                            popup=f"Status: {row['location_status']}"
                        ).add_to(m)
                else:
                    st.info("Large dataset: Plotting simple markers.")
                    folium.CircleMarker(location=[center_lat, center_lon], radius=1, color='gray').add_to(m)

                st_folium(m, width=None, height=500, key="main_map")

                st.write("### Valid Points (Outside)")
                outside_points = gdf_points[gdf_points['location_status'] == 'Outside'].drop(columns='geometry')
                st.dataframe(outside_points, use_container_width=True)
                st.download_button("Download 'Outside' Points", outside_points.to_csv(index=False).encode('utf-8'), "outside_points.csv", "text/csv")

            with tab2:
                st.warning(f"Found {len(df_zero)} rows where coordinates are exactly (0, 0).")
                st.markdown("These are often default values indicating **missing GPS data**.")
                st.dataframe(df_zero, use_container_width=True)
                if not df_zero.empty:
                    st.download_button("Download Zero-Coord Rows", df_zero.to_csv(index=False).encode('utf-8'), "zero_coordinate_rows.csv", "text/csv")

            with tab3:
                st.error(f"Found {len(df_invalid)} rows with invalid coordinates.")
                st.markdown("These rows have text errors or impossible numbers (e.g., Lat > 90).")
                st.dataframe(df_invalid, use_container_width=True)
                if not df_invalid.empty:
                    st.download_button("Download Invalid Rows", df_invalid.to_csv(index=False).encode('utf-8'), "invalid_rows.csv", "text/csv")

            with tab4:
                st.metric("Total Rows", res['df_raw_len'])
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Valid Rows", len(gdf_points))
                c2.metric("Zero (0,0) Rows", len(df_zero))
                c3.metric("Invalid Rows", len(df_invalid))
                c4.metric("Outside Boundary", len(gdf_points[gdf_points['location_status'] == 'Outside']))