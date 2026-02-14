import streamlit as st
import pandas as pd
import geopandas as gpd
import folium
from streamlit_folium import st_folium
from shapely.geometry import Point
import numpy as np
from folium.plugins import MarkerCluster

# Set page configuration
st.set_page_config(page_title="Geo Spatial Filter", layout="wide")

st.title("📍 GeoJSON vs. CSV Point Analyzer")

st.markdown("""
**Two Analysis Modes:**
1. **Data Validation Only** - Check for zero, valid, and invalid coordinates (no GeoJSON needed)
2. **Spatial Analysis** - Find points inside/outside a GeoJSON polygon (optional)
""")

# --- Step 1: File Upload ---
sep = ","  # Initialize outside container for global access

# Opening div for Step 1 with inline styles
st.markdown("""
<div style="background: linear-gradient(to right, #f0ebff 0%, #faf8ff 100%); 
            border-left: 10px solid #667eea; 
            padding: 25px; 
            padding-left: 30px; 
            border-radius: 10px; 
            margin: 20px 0; 
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
    <h3 style="color: #2c3e50; margin-top: 0; font-weight: 600;">📂 Step 1: Upload Your Data File</h3>
""", unsafe_allow_html=True)

csv_file = st.file_uploader("Upload CSV/Excel (Points)", type=['csv', 'txt', 'xlsx', 'xls'])

# --- Step 1.5: CSV Delimiter Settings ---
if csv_file is not None:
    # Only show delimiter settings for CSV/TXT files, not Excel
    file_extension = csv_file.name.split('.')[-1].lower()
    if file_extension not in ['xlsx', 'xls']:
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

# Close Step 1 div
st.markdown("</div>", unsafe_allow_html=True)

# --- Session State ---
if 'validation_results' not in st.session_state:
    st.session_state.validation_results = None
if 'spatial_results' not in st.session_state:
    st.session_state.spatial_results = None

# --- Step 2: Process Data File ---
if csv_file is not None:
    # Opening div for Step 2
    st.markdown("""
    <div style="background: linear-gradient(to right, #fff0f6 0%, #fff8fa 100%); 
                border-left: 10px solid #f5576c; 
                padding: 25px; 
                padding-left: 30px; 
                border-radius: 10px; 
                margin: 20px 0; 
                box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
        <h3 style="color: #2c3e50; margin-top: 0; font-weight: 600;">🔍 Step 2: Configure & Validate Coordinates</h3>
    """, unsafe_allow_html=True)
    
    with st.container():
        # Get Excel sheet names
        @st.cache_data
        def get_excel_sheets(file_bytes, file_name):
            """Get list of sheet names from Excel file"""
            file_extension = file_name.split('.')[-1].lower()
            
            if file_extension in ['xlsx', 'xls']:
                from io import BytesIO
                excel_file = pd.ExcelFile(BytesIO(file_bytes))
                return excel_file.sheet_names
            return None
        
        # Load PREVIEW ONLY (first 100 rows) for column selection
        @st.cache_data
        def load_preview(file_bytes, file_name, separator, sheet_name=None, nrows=100):
            """Load only first N rows for preview"""
            file_extension = file_name.split('.')[-1].lower()
            
            if file_extension in ['xlsx', 'xls']:
                from io import BytesIO
                df = pd.read_excel(BytesIO(file_bytes), dtype=str, nrows=nrows, sheet_name=sheet_name)
                return df, 'Excel'
            else:
                from io import StringIO
                df = pd.read_csv(StringIO(file_bytes.decode('utf-8')), sep=separator, dtype=str, nrows=nrows)
                return df, 'CSV'
        
        # Load full file (cached)
        @st.cache_data
        def load_full_file(file_bytes, file_name, separator, sheet_name=None):
            """Load complete file - only called when validation button is clicked"""
            file_extension = file_name.split('.')[-1].lower()
            
            if file_extension in ['xlsx', 'xls']:
                from io import BytesIO
                df = pd.read_excel(BytesIO(file_bytes), dtype=str, sheet_name=sheet_name)
                return df, 'Excel'
            else:
                from io import StringIO
                df = pd.read_csv(StringIO(file_bytes.decode('utf-8')), sep=separator, dtype=str)
                return df, 'CSV'
        
        try:
            csv_file.seek(0)
            file_bytes = csv_file.read()
            
            # Check if Excel file with multiple sheets
            file_extension = csv_file.name.split('.')[-1].lower()
            selected_sheet = None
            
            if file_extension in ['xlsx', 'xls']:
                sheet_names = get_excel_sheets(file_bytes, csv_file.name)
                
                if sheet_names and len(sheet_names) > 1:
                    st.info(f"📊 This Excel file has {len(sheet_names)} sheets")
                    selected_sheet = st.selectbox(
                        "Select sheet to analyze:",
                        options=sheet_names,
                        index=0,
                        key="sheet_selector"
                    )
                elif sheet_names:
                    selected_sheet = sheet_names[0]
            
            # Load preview only for UI
            df_preview, file_type = load_preview(file_bytes, csv_file.name, sep, sheet_name=selected_sheet, nrows=100)
            
            if selected_sheet:
                st.success(f"✅ Loaded preview of {file_type} file: {csv_file.name} - Sheet: '{selected_sheet}' (showing first 100 rows for column selection)")
            else:
                st.success(f"✅ Loaded preview of {file_type} file: {csv_file.name} (showing first 100 rows for column selection)")
            
            st.info("💡 Full file will be processed when you click 'Validate Data Quality'")
            
            # Use preview for UI
            df = df_preview
        except Exception as e:
            st.error(f"Error reading file: {e}")
            st.stop()
        
        # --- Data Validation Preview ---
        st.divider()
        st.subheader("📋 Data Preview & Validation")
        
        with st.expander("📊 View Data Quality Summary", expanded=False):
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Total Rows", len(df))
            col_b.metric("Total Columns", len(df.columns))
            col_c.metric("File Size", f"{csv_file.size / (1024*1024):.2f} MB")
            
            st.write("**Column Names:**")
            st.write(", ".join(df.columns.tolist()))
            
            st.write("**First 5 Rows:**")
            st.dataframe(df.head(), use_container_width=True)

        # Column Selectors
        columns = df.columns.tolist()
        c1, c2 = st.columns(2)
        with c1:
            x_col = st.selectbox("Select X Column (Longitude)", options=columns, index=0, key="x_col_select")
        with c2:
            y_col = st.selectbox("Select Y Column (Latitude)", options=columns, index=1 if len(columns) > 1 else 0, key="y_col_select")
        
        if st.button("✅ Validate Data Quality", type="primary", use_container_width=True):
            with st.spinner("Loading full file and analyzing coordinate quality..."):
                
                # Load FULL file now
                df_full, _ = load_full_file(file_bytes, csv_file.name, sep, sheet_name=selected_sheet)
                st.info(f"📊 Processing {len(df_full):,} total rows...")
                
                # 1. Clean Data (Handle commas)
                df_clean = df_full.copy()
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
                # A. Empty/Null - Missing coordinates
                empty_mask = df_clean[x_col].isna() | df_clean[y_col].isna()
                
                # B. Zero Coordinates (0,0) - Often default sensor values
                zero_mask = (df_clean[x_col] == 0) & (df_clean[y_col] == 0)
                
                # C. Valid Range
                # Valid range: Lon -180 to 180, Lat -90 to 90
                valid_range_mask = (
                    (df_clean[x_col].between(-180, 180)) & 
                    (df_clean[y_col].between(-90, 90))
                )
                # Valid is in range AND not zero AND not empty
                valid_mask = valid_range_mask & (~zero_mask) & (~empty_mask)

                # D. Invalid - everything else (text, out of range, etc.)
                # Create DataFrames
                df_valid = df_clean[valid_mask].copy()
                df_zero = df_full[zero_mask].copy()
                df_empty = df_full[empty_mask].copy()
                df_invalid = df_full[~(valid_mask | zero_mask | empty_mask)].copy()
                
                # Add diagnostic columns to invalid data
                if not df_invalid.empty:
                    df_invalid['_validation_issue'] = ''
                    
                    # Check each invalid row for reason
                    for idx in df_invalid.index:
                        reasons = []
                        x_val = df_clean.loc[idx, x_col]
                        y_val = df_clean.loc[idx, y_col]
                        
                        if pd.isna(x_val) or pd.isna(y_val):
                            reasons.append("Empty/Null value")
                        elif not isinstance(x_val, (int, float)):
                            reasons.append(f"Cannot convert to number")
                        elif x_val < -180 or x_val > 180:
                            reasons.append(f"Lon out of range ({x_val})")
                        elif y_val < -90 or y_val > 90:
                            reasons.append(f"Lat out of range ({y_val})")
                        
                        df_invalid.loc[idx, '_validation_issue'] = '; '.join(reasons) if reasons else 'Unknown'

                # Save validation results
                st.session_state.validation_results = {
                    'df_valid': df_valid,
                    'df_invalid': df_invalid,
                    'df_zero': df_zero,
                    'df_empty': df_empty,
                    'df_raw_len': len(df_full),
                    'x_col': x_col,
                    'y_col': y_col,
                    'diagnostics': {
                        'empty_count': empty_mask.sum(),
                        'out_of_range_lon': ((df_clean[x_col] < -180) | (df_clean[x_col] > 180)).sum(),
                        'out_of_range_lat': ((df_clean[y_col] < -90) | (df_clean[y_col] > 90)).sum()
                    }
                }
                st.success("✅ Data validation complete!")
    
    # Close Step 2 div
    st.markdown("</div>", unsafe_allow_html=True)
    
    # --- Step 3: Spatial Analysis (Optional) ---
    if st.session_state.validation_results:
        # Opening div for Step 3
        st.markdown("""
        <div style="background: linear-gradient(to right, #e6f9ff 0%, #f0fcff 100%); 
                    border-left: 10px solid #00f2fe; 
                    padding: 25px; 
                    padding-left: 30px; 
                    border-radius: 10px; 
                    margin: 20px 0; 
                    box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
            <h3 style="color: #2c3e50; margin-top: 0; font-weight: 600;">🗺️ Step 3: Spatial Analysis (Optional)</h3>
        """, unsafe_allow_html=True)
        
        with st.container():
            st.info("Upload a GeoJSON polygon to find which valid points are inside/outside the boundary.")
            
            geojson_file = st.file_uploader("Upload GeoJSON (Polygon) - Optional", type=['geojson', 'json'])
            
            if geojson_file is not None:
                if st.button("🎯 Run Spatial Analysis", type="secondary", use_container_width=True):
                    with st.spinner("Analyzing spatial relationships..."):
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
                        
                        # Get validation results
                        val_res = st.session_state.validation_results
                        df_valid = val_res['df_valid']
                        x_col = val_res['x_col']
                        y_col = val_res['y_col']
                        
                        # Spatial Join
                        if not df_valid.empty:
                            geometry = [Point(xy) for xy in zip(df_valid[x_col], df_valid[y_col])]
                            gdf_points = gpd.GeoDataFrame(df_valid, geometry=geometry, crs="EPSG:4326")
                            
                            polygon_union = gdf_polygon.unary_union
                            gdf_points['location_status'] = gdf_points.geometry.within(polygon_union).map({True: 'Inside', False: 'Outside'})
                            
                            # Save spatial results
                            st.session_state.spatial_results = {
                                'gdf_points': gdf_points,
                                'gdf_polygon': gdf_polygon
                            }
                            st.success("✅ Spatial analysis complete!")
                        else:
                            st.error("No valid coordinates to analyze spatially.")
        
        # Close Step 3 div
        st.markdown("</div>", unsafe_allow_html=True)

# --- Results Section (White Background) ---
if st.session_state.validation_results:
    st.markdown('<div class="results-section">', unsafe_allow_html=True)
    st.markdown("### 📊 Validation Results")
    
    val_res = st.session_state.validation_results
    spatial_res = st.session_state.spatial_results
    
    df_valid = val_res['df_valid']
    df_invalid = val_res['df_invalid']
    df_zero = val_res['df_zero']
    df_empty = val_res['df_empty']
    x_col = val_res['x_col']
    y_col = val_res['y_col']
    
    # Show tabs based on whether spatial analysis is done
    if spatial_res:
        # SPATIAL MODE: Show all tabs including map
        gdf_points = spatial_res['gdf_points']
        gdf_polygon = spatial_res['gdf_polygon']
        
        tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
            "🗺️ Map", 
            "✅ All Valid Data", 
            "🔴 Valid but Outside", 
            "0️⃣ Zero Coordinates",
            "📭 Empty/Null",
            "❌ Invalid Data", 
            "📊 Summary"
        ])
    else:
        # VALIDATION ONLY MODE: Show only data quality tabs
        tab2, tab4, tab5, tab6, tab7 = st.tabs([
            "✅ Valid Coordinates",
            "0️⃣ Zero Coordinates",
            "📭 Empty/Null",
            "❌ Invalid Data", 
            "📊 Summary"
        ])
    
    # --- Render Tab Content ---
    if spatial_res:
            # SPATIAL MODE: Show all tabs including map
            gdf_points = spatial_res['gdf_points']
            gdf_polygon = spatial_res['gdf_polygon']
            
            with tab1:
                gdf_points = spatial_res['gdf_points']
                gdf_polygon = spatial_res['gdf_polygon']
                
                # Map Preparation
                center_lat = gdf_points[y_col].mean()
                center_lon = gdf_points[x_col].mean()
                
                m = folium.Map(location=[center_lat, center_lon], zoom_start=12, tiles="CartoDB positron")
                folium.GeoJson(gdf_polygon, style_function=lambda x: {'fillColor': 'blue', 'color': 'blue', 'fillOpacity': 0.1}).add_to(m)

                # Performance-optimized markers with clustering
                num_points = len(gdf_points)
                
                if num_points < 500:
                    # Small dataset: Individual markers
                    for idx, row in gdf_points.iterrows():
                        color = '#2ecc71' if row['location_status'] == 'Inside' else '#e74c3c'
                        folium.CircleMarker(
                            location=[row[y_col], row[x_col]], 
                            radius=4, 
                            color=color, 
                            fill=True, 
                            fill_color=color, 
                            fill_opacity=0.8,
                            popup=f"Status: {row['location_status']}"
                        ).add_to(m)
                    st.success(f"✅ Showing {num_points} individual markers")
                
                elif num_points < 10000:
                    # Medium dataset: Use MarkerCluster for better performance
                    st.info(f"📍 Showing {num_points} points with clustering (click clusters to zoom in)")
                    
                    # Create separate clusters for inside/outside
                    marker_cluster_inside = MarkerCluster(name='Inside Points').add_to(m)
                    marker_cluster_outside = MarkerCluster(name='Outside Points').add_to(m)
                    
                    for idx, row in gdf_points.iterrows():
                        if row['location_status'] == 'Inside':
                            folium.CircleMarker(
                                location=[row[y_col], row[x_col]],
                                radius=4,
                                color='#2ecc71',
                                fill=True,
                                fill_color='#2ecc71',
                                fill_opacity=0.8,
                                popup=f"Status: Inside"
                            ).add_to(marker_cluster_inside)
                        else:
                            folium.CircleMarker(
                                location=[row[y_col], row[x_col]],
                                radius=4,
                                color='#e74c3c',
                                fill=True,
                                fill_color='#e74c3c',
                                fill_opacity=0.8,
                                popup=f"Status: Outside"
                            ).add_to(marker_cluster_outside)
                    
                    folium.LayerControl().add_to(m)
                
                else:
                    # Large dataset: Sample points for visualization
                    sample_size = 5000
                    st.warning(f"⚠️ Large dataset ({num_points} points). Showing random sample of {sample_size} points for performance.")
                    
                    sampled_points = gdf_points.sample(n=sample_size, random_state=42)
                    marker_cluster = MarkerCluster().add_to(m)
                    
                    for idx, row in sampled_points.iterrows():
                        color = '#2ecc71' if row['location_status'] == 'Inside' else '#e74c3c'
                        folium.CircleMarker(
                            location=[row[y_col], row[x_col]],
                            radius=3,
                            color=color,
                            fill=True,
                            fill_color=color,
                            fill_opacity=0.7,
                            popup=f"Status: {row['location_status']}"
                        ).add_to(marker_cluster)

                st_folium(m, width=None, height=500, key="main_map")
                
                # Legend
                st.markdown("""
                **Legend:**
                - 🟢 Green markers = Inside polygon
                - 🔴 Red markers = Outside polygon
                - 🔵 Blue shaded area = GeoJSON polygon boundary
                """)

            with tab2:
                st.success(f"All valid coordinate data ({len(gdf_points)} rows)")
                st.markdown("This includes points both **inside** and **outside** the polygon boundary.")
                
                # Prepare data without geometry column
                all_valid_data = gdf_points.drop(columns='geometry').copy()
                
                # Display with status filter
                status_filter = st.radio("Filter by location:", ["All", "Inside Only", "Outside Only"], horizontal=True)
                if status_filter == "Inside Only":
                    display_data = all_valid_data[all_valid_data['location_status'] == 'Inside']
                elif status_filter == "Outside Only":
                    display_data = all_valid_data[all_valid_data['location_status'] == 'Outside']
                else:
                    display_data = all_valid_data
                
                st.dataframe(display_data, use_container_width=True)
                st.download_button(
                    "Download All Valid Data", 
                    all_valid_data.to_csv(index=False).encode('utf-8'), 
                    "all_valid_points.csv", 
                    "text/csv"
                )

            with tab3:
                outside_points = gdf_points[gdf_points['location_status'] == 'Outside'].drop(columns='geometry')
                st.warning(f"Found {len(outside_points)} valid points that fall OUTSIDE the polygon boundary")
                st.markdown("These coordinates are valid (proper lat/lon format) but don't fall within your GeoJSON polygon.")
                st.dataframe(outside_points, use_container_width=True)
                if not outside_points.empty:
                    st.download_button(
                        "Download 'Outside' Points", 
                        outside_points.to_csv(index=False).encode('utf-8'), 
                        "outside_points.csv", 
                        "text/csv"
                    )

            with tab4:
                st.warning(f"Found {len(df_zero)} rows where coordinates are exactly (0, 0).")
                st.markdown("These are often default values indicating **missing GPS data**.")
                st.dataframe(df_zero, use_container_width=True)
                if not df_zero.empty:
                    st.download_button("Download Zero-Coord Rows", df_zero.to_csv(index=False).encode('utf-8'), "zero_coordinate_rows.csv", "text/csv")

            with tab5:
                st.info(f"Found {len(df_empty)} rows with empty/null coordinates.")
                st.markdown("These rows have missing coordinate values (blank cells).")
                st.dataframe(df_empty, use_container_width=True)
                if not df_empty.empty:
                    st.download_button("Download Empty Rows", df_empty.to_csv(index=False).encode('utf-8'), "empty_coordinates.csv", "text/csv")

            with tab6:
                st.error(f"Found {len(df_invalid)} rows with invalid coordinates.")
                st.markdown("These rows have text errors or impossible numbers (e.g., Lat > 90).")
                st.dataframe(df_invalid, use_container_width=True)
                if not df_invalid.empty:
                    st.download_button("Download Invalid Rows", df_invalid.to_csv(index=False).encode('utf-8'), "invalid_rows.csv", "text/csv")

            with tab7:
                st.metric("Total Rows", val_res['df_raw_len'])
                c1, c2, c3, c4, c5, c6 = st.columns(6)
                inside_count = len(gdf_points[gdf_points['location_status'] == 'Inside'])
                outside_count = len(gdf_points[gdf_points['location_status'] == 'Outside'])
                
                c1.metric("Valid Rows", len(gdf_points))
                c2.metric("✅ Inside Polygon", inside_count)
                c3.metric("🔴 Outside Polygon", outside_count)
                c4.metric("Zero (0,0)", len(df_zero))
                c5.metric("Empty/Null", len(df_empty))
                c6.metric("Invalid", len(df_invalid))
    
    else:
            # VALIDATION ONLY MODE: Show only data quality tabs
            with tab2:
                st.success(f"Valid coordinate data ({len(df_valid)} rows)")
                st.markdown("These coordinates pass validation (proper lat/lon format).")
                st.dataframe(df_valid, use_container_width=True)
                st.download_button(
                    "Download Valid Data", 
                    df_valid.to_csv(index=False).encode('utf-8'), 
                    "valid_coordinates.csv", 
                    "text/csv"
                )
            
            with tab4:
                st.warning(f"Found {len(df_zero)} rows where coordinates are exactly (0, 0).")
                st.markdown("These are often default values indicating **missing GPS data**.")
                st.dataframe(df_zero, use_container_width=True)
                if not df_zero.empty:
                    st.download_button("Download Zero-Coord Rows", df_zero.to_csv(index=False).encode('utf-8'), "zero_coordinate_rows.csv", "text/csv")
            
            with tab5:
                st.info(f"Found {len(df_empty)} rows with empty/null coordinates.")
                st.markdown("These rows have missing coordinate values (blank cells).")
                st.dataframe(df_empty, use_container_width=True)
                if not df_empty.empty:
                    st.download_button("Download Empty Rows", df_empty.to_csv(index=False).encode('utf-8'), "empty_coordinates.csv", "text/csv")
            
            with tab6:
                st.error(f"Found {len(df_invalid)} rows with invalid coordinates.")
                
                # Show diagnostic summary
                if 'diagnostics' in val_res and not df_invalid.empty:
                    diag = val_res['diagnostics']
                    st.markdown("### 🔍 Why is my data invalid?")
                    
                    col1, col2 = st.columns(2)
                    col1.metric("Longitude Out of Range", diag['out_of_range_lon'], help="Valid: -180 to 180")
                    col2.metric("Latitude Out of Range", diag['out_of_range_lat'], help="Valid: -90 to 90")
                    
                    st.markdown("""
                    **Common Issues:**
                    - **Swapped columns** - Check if you selected Lat/Lon correctly (Lat should be -90 to 90, Lon -180 to 180)
                    - **Wrong format** - UTM, DMS (degrees-minutes-seconds) not supported yet
                    - **Text values** - Non-numeric data in coordinate columns
                    """)
                
                st.markdown("---")
                st.dataframe(df_invalid, use_container_width=True)
                if not df_invalid.empty:
                    st.download_button("Download Invalid Rows", df_invalid.to_csv(index=False).encode('utf-8'), "invalid_rows.csv", "text/csv")
            
            with tab7:
                st.metric("Total Rows", val_res['df_raw_len'])
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("✅ Valid Rows", len(df_valid))
                c2.metric("0️⃣ Zero (0,0)", len(df_zero))
                c3.metric("📭 Empty/Null", len(df_empty))
                c4.metric("❌ Invalid", len(df_invalid))
    st.markdown('</div>', unsafe_allow_html=True)  # Close Results Section
