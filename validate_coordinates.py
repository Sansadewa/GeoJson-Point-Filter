#!/usr/bin/env python3
"""
Command-line Coordinate Validator
Validates CSV/Excel files for coordinate quality without Streamlit.
"""

import argparse
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import numpy as np
import sys
from pathlib import Path


def clean_coord(val):
    """Clean and convert coordinate value to float"""
    if pd.isna(val):
        return np.nan
    val = str(val).strip().replace(',', '.')
    try:
        return float(val)
    except:
        return np.nan


def validate_coordinates(input_file, x_col, y_col, output_dir=None, geojson_file=None, separator=','):
    """
    Validate coordinates in a CSV/Excel file
    
    Args:
        input_file: Path to CSV or Excel file
        x_col: Column name for longitude (X)
        y_col: Column name for latitude (Y)
        output_dir: Directory to save output files (default: same as input)
        geojson_file: Optional GeoJSON file for spatial analysis
        separator: CSV delimiter (default: ',')
    """
    
    print(f"\n{'='*60}")
    print(f"COORDINATE VALIDATOR")
    print(f"{'='*60}\n")
    
    # 1. Load data file
    print(f"📂 Loading file: {input_file}")
    file_path = Path(input_file)
    
    if not file_path.exists():
        print(f"❌ Error: File not found: {input_file}")
        sys.exit(1)
    
    try:
        if file_path.suffix.lower() in ['.xlsx', '.xls']:
            df = pd.read_excel(input_file, dtype=str)
            file_type = "Excel"
        else:
            df = pd.read_csv(input_file, sep=separator, dtype=str)
            file_type = "CSV"
        
        print(f"✅ Loaded {file_type} file: {len(df):,} rows, {len(df.columns)} columns")
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        sys.exit(1)
    
    # Check if columns exist
    if x_col not in df.columns:
        print(f"❌ Error: Column '{x_col}' not found in file")
        print(f"Available columns: {', '.join(df.columns)}")
        sys.exit(1)
    
    if y_col not in df.columns:
        print(f"❌ Error: Column '{y_col}' not found in file")
        print(f"Available columns: {', '.join(df.columns)}")
        sys.exit(1)
    
    # 2. Clean and categorize data
    print(f"\n🔍 Validating coordinates...")
    df_clean = df.copy()
    df_clean[x_col] = df_clean[x_col].apply(clean_coord)
    df_clean[y_col] = df_clean[y_col].apply(clean_coord)
    
    # Categorize
    empty_mask = df_clean[x_col].isna() | df_clean[y_col].isna()
    zero_mask = (df_clean[x_col] == 0) & (df_clean[y_col] == 0)
    valid_range_mask = (
        (df_clean[x_col].between(-180, 180)) & 
        (df_clean[y_col].between(-90, 90))
    )
    valid_mask = valid_range_mask & (~zero_mask) & (~empty_mask)
    
    df_valid = df_clean[valid_mask].copy()
    df_zero = df[zero_mask].copy()
    df_empty = df[empty_mask].copy()
    df_invalid = df[~(valid_mask | zero_mask | empty_mask)].copy()
    
    # 3. Print summary
    print(f"\n{'='*60}")
    print(f"VALIDATION SUMMARY")
    print(f"{'='*60}")
    print(f"Total Rows:        {len(df):,}")
    print(f"✅ Valid:          {len(df_valid):,} ({len(df_valid)/len(df)*100:.1f}%)")
    print(f"0️⃣  Zero (0,0):     {len(df_zero):,} ({len(df_zero)/len(df)*100:.1f}%)")
    print(f"📭 Empty/Null:     {len(df_empty):,} ({len(df_empty)/len(df)*100:.1f}%)")
    print(f"❌ Invalid:        {len(df_invalid):,} ({len(df_invalid)/len(df)*100:.1f}%)")
    print(f"{'='*60}\n")
    
    # Diagnostics
    out_of_range_lon = ((df_clean[x_col] < -180) | (df_clean[x_col] > 180)).sum()
    out_of_range_lat = ((df_clean[y_col] < -90) | (df_clean[y_col] > 90)).sum()
    
    if len(df_invalid) > 0:
        print(f"⚠️  INVALID DATA BREAKDOWN:")
        print(f"   - Longitude out of range: {out_of_range_lon}")
        print(f"   - Latitude out of range:  {out_of_range_lat}")
        print()
    
    # 4. Spatial analysis (if GeoJSON provided)
    df_inside = None
    df_outside = None
    
    if geojson_file and len(df_valid) > 0:
        print(f"🗺️  Running spatial analysis with GeoJSON: {geojson_file}")
        try:
            gdf_polygon = gpd.read_file(geojson_file)
            if gdf_polygon.crs is not None:
                gdf_polygon = gdf_polygon.to_crs(epsg=4326)
            else:
                gdf_polygon.set_crs(epsg=4326, inplace=True)
            
            # Create GeoDataFrame from valid points
            geometry = [Point(xy) for xy in zip(df_valid[x_col], df_valid[y_col])]
            gdf_points = gpd.GeoDataFrame(df_valid, geometry=geometry, crs="EPSG:4326")
            
            # Spatial join
            polygon_union = gdf_polygon.unary_union
            gdf_points['location_status'] = gdf_points.geometry.within(polygon_union).map({True: 'Inside', False: 'Outside'})
            
            df_inside = gdf_points[gdf_points['location_status'] == 'Inside'].drop(columns='geometry')
            df_outside = gdf_points[gdf_points['location_status'] == 'Outside'].drop(columns='geometry')
            
            print(f"   ✅ Inside polygon:  {len(df_inside):,} ({len(df_inside)/len(df_valid)*100:.1f}% of valid)")
            print(f"   🔴 Outside polygon: {len(df_outside):,} ({len(df_outside)/len(df_valid)*100:.1f}% of valid)")
            print()
        except Exception as e:
            print(f"   ❌ Error during spatial analysis: {e}")
            print()
    
    # 5. Save output files
    if output_dir is None:
        output_dir = file_path.parent
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"💾 Saving output files to: {output_dir}")
    
    base_name = file_path.stem
    saved_files = []
    
    if len(df_valid) > 0:
        output_file = output_dir / f"{base_name}_valid.csv"
        df_valid.to_csv(output_file, index=False)
        saved_files.append(f"   ✅ {output_file.name} ({len(df_valid):,} rows)")
    
    if len(df_zero) > 0:
        output_file = output_dir / f"{base_name}_zero.csv"
        df_zero.to_csv(output_file, index=False)
        saved_files.append(f"   0️⃣  {output_file.name} ({len(df_zero):,} rows)")
    
    if len(df_empty) > 0:
        output_file = output_dir / f"{base_name}_empty.csv"
        df_empty.to_csv(output_file, index=False)
        saved_files.append(f"   📭 {output_file.name} ({len(df_empty):,} rows)")
    
    if len(df_invalid) > 0:
        output_file = output_dir / f"{base_name}_invalid.csv"
        df_invalid.to_csv(output_file, index=False)
        saved_files.append(f"   ❌ {output_file.name} ({len(df_invalid):,} rows)")
    
    if df_inside is not None and len(df_inside) > 0:
        output_file = output_dir / f"{base_name}_inside_polygon.csv"
        df_inside.to_csv(output_file, index=False)
        saved_files.append(f"   ✅ {output_file.name} ({len(df_inside):,} rows)")
    
    if df_outside is not None and len(df_outside) > 0:
        output_file = output_dir / f"{base_name}_outside_polygon.csv"
        df_outside.to_csv(output_file, index=False)
        saved_files.append(f"   🔴 {output_file.name} ({len(df_outside):,} rows)")
    
    for file_info in saved_files:
        print(file_info)
    
    print(f"\n✅ Processing complete!\n")


def main():
    parser = argparse.ArgumentParser(
        description='Validate coordinate data in CSV/Excel files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic validation
  python validate_coordinates.py data.csv -x longitude -y latitude

  # With custom separator
  python validate_coordinates.py data.csv -x lon -y lat -s ";"

  # With spatial analysis
  python validate_coordinates.py data.csv -x lon -y lat -g boundary.geojson

  # Specify output directory
  python validate_coordinates.py data.csv -x lon -y lat -o ./results

  # List columns in file
  python validate_coordinates.py data.csv --list-columns
        """
    )
    
    parser.add_argument('input_file', help='Input CSV or Excel file')
    parser.add_argument('-x', '--x-column', dest='x_col', help='Column name for longitude (X coordinate)')
    parser.add_argument('-y', '--y-column', dest='y_col', help='Column name for latitude (Y coordinate)')
    parser.add_argument('-g', '--geojson', dest='geojson_file', help='GeoJSON file for spatial analysis (optional)')
    parser.add_argument('-o', '--output', dest='output_dir', help='Output directory (default: same as input file)')
    parser.add_argument('-s', '--separator', dest='separator', default=',', help='CSV separator/delimiter (default: ",")')
    parser.add_argument('--list-columns', action='store_true', help='List all columns in the file and exit')
    
    args = parser.parse_args()
    
    # List columns mode
    if args.list_columns:
        file_path = Path(args.input_file)
        if not file_path.exists():
            print(f"❌ Error: File not found: {args.input_file}")
            sys.exit(1)
        
        try:
            if file_path.suffix.lower() in ['.xlsx', '.xls']:
                df = pd.read_excel(args.input_file, nrows=0)
            else:
                df = pd.read_csv(args.input_file, sep=args.separator, nrows=0)
            
            print(f"\n📋 Columns in {file_path.name}:")
            for i, col in enumerate(df.columns, 1):
                print(f"  {i}. {col}")
            print()
        except Exception as e:
            print(f"❌ Error reading file: {e}")
            sys.exit(1)
        
        sys.exit(0)
    
    # Validate required arguments
    if not args.x_col or not args.y_col:
        parser.error("Both -x/--x-column and -y/--y-column are required (or use --list-columns to see available columns)")
    
    # Run validation
    validate_coordinates(
        input_file=args.input_file,
        x_col=args.x_col,
        y_col=args.y_col,
        output_dir=args.output_dir,
        geojson_file=args.geojson_file,
        separator=args.separator
    )


if __name__ == '__main__':
    main()
