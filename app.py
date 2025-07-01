import streamlit as st
import geopandas as gpd
import pandas as pd
from shapely.geometry import box, Point, MultiPolygon
import simplekml
from io import BytesIO
import math

st.set_page_config(layout="wide")
st.title("📍 Grid Identifikasi Homepass (Max 16 per Area 250m²)")

def load_kml(uploaded_file):
    try:
        gdf = gpd.read_file(uploaded_file, driver='KML')
        return gdf[gdf.geometry.type == 'Point']
    except Exception as e:
        st.error(f"Gagal memuat KML: {str(e)}")
        return None

def create_aligned_grids(gdf, grid_size=15.8):
    bounds = gdf.total_bounds
    minx, miny, maxx, maxy = bounds
    
    cols = math.ceil((maxx - minx) / grid_size)
    rows = math.ceil((maxy - miny) / grid_size)
    
    polygons = []
    for i in range(cols):
        for j in range(rows):
            x = minx + i * grid_size
            y = miny + j * grid_size
            polygons.append(box(x, y, x + grid_size, y + grid_size))
    
    return gpd.GeoDataFrame(geometry=polygons, crs=gdf.crs)

def create_fat_areas_aligned(grid_with_hp, gdf):
    fat_areas = []
    homepass_groups = {}
    fat_index = 1
    
    grid_with_hp['row'] = grid_with_hp.geometry.apply(lambda g: int(round(g.centroid.y / 15.8)))
    grid_with_hp['col'] = grid_with_hp.geometry.apply(lambda g: int(round(g.centroid.x / 15.8)))
    
    grid_sorted = grid_with_hp.sort_values(['row', 'col'])
    
    current_fat = []
    current_hp = 0
    current_row = None
    
    for _, row in grid_sorted.iterrows():
        if current_row is None:
            current_row = row['row']
        
        if row['row'] != current_row or (current_hp + row['homepass'] > 16 and current_hp > 0):
            if current_fat:
                combined_geom = MultiPolygon(current_fat).convex_hull
                fat_areas.append({
                    'geometry': combined_geom,
                    'homepass': current_hp,
                    'label': f'FAT {fat_index}',
                    'color': 'green' if current_hp >= 16 else 'red'
                })
                
                points_in_fat = gdf[gdf.geometry.within(combined_geom)]
                homepass_groups[f'FAT {fat_index}'] = points_in_fat
                
                fat_index += 1
                current_fat = []
                current_hp = 0
            
            current_row = row['row']
        
        current_fat.append(row['geometry'])
        current_hp += row['homepass']
    
    if current_fat:
        combined_geom = MultiPolygon(current_fat).convex_hull
        fat_areas.append({
            'geometry': combined_geom,
            'homepass': current_hp,
            'label': f'FAT {fat_index}',
            'color': 'green' if current_hp >= 16 else 'red'
        })
        
        points_in_fat = gdf[gdf.geometry.within(combined_geom)]
        homepass_groups[f'FAT {fat_index}'] = points_in_fat
    
    return gpd.GeoDataFrame(fat_areas, crs=grid_with_hp.crs), homepass_groups

# UI
uploaded_file = st.file_uploader("📤 Upload file KML berisi titik Homepass", type=["kml"])

if uploaded_file:
    gdf = load_kml(uploaded_file)
    
    if gdf is None or len(gdf) == 0:
        st.error("❌ Tidak ada data titik yang valid dalam file KML")
        st.stop()
    
    st.success(f"✅ Berhasil memuat {len(gdf)} titik Homepass")
    
    # Konversi ke UTM
    gdf = gdf.to_crs(epsg=32748)
    
    # Buat grid yang teratur
    grid = create_aligned_grids(gdf)
    
    # Hitung titik per grid
    joined = gpd.sjoin(grid, gdf, how='left', predicate='contains')
    counts = joined.groupby(joined.index).size()
    grid['homepass'] = counts.reindex(grid.index, fill_value=0).astype(int)
    
    # Filter grid dengan HP
    grid_with_hp = grid[grid['homepass'] > 0].copy()
    
    if len(grid_with_hp) == 0:
        st.error("❌ Tidak ada titik Homepass yang masuk dalam grid manapun")
        st.stop()
    
    # Buat FAT area yang teratur
    fat_areas, homepass_groups = create_fat_areas_aligned(grid_with_hp, gdf)
    fat_areas_wgs = fat_areas.to_crs(epsg=4326)
    
    # Buat KML dengan struktur folder
    kml = simplekml.Kml()
    
    # Folder FAT AREA
    fat_folder = kml.newfolder(name="FAT AREA")
    for _, row in fat_areas_wgs.iterrows():
        poly = fat_folder.newpolygon(name=row['label'])
        poly.style.polystyle.color = simplekml.Color.green if row['color'] == 'green' else simplekml.Color.red
        poly.style.linestyle.color = simplekml.Color.green if row['color'] == 'green' else simplekml.Color.red
        poly.style.linestyle.width = 2
        
        if hasattr(row.geometry, 'geoms'):
            for geom in row.geometry.geoms:
                poly.outerboundaryis = [(x,y) for x,y in geom.exterior.coords]
        else:
            poly.outerboundaryis = [(x,y) for x,y in row.geometry.exterior.coords]
        
        poly.description = f"Jumlah HP: {row['homepass']}"
    
    # Folder HOMEPASS
    hp_folder = kml.newfolder(name="HOMEPASS")
    for fat_name, points in homepass_groups.items():
        fat_hp_folder = hp_folder.newfolder(name=fat_name)
        points_wgs = points.to_crs(epsg=4326)
        
        for _, point in points_wgs.iterrows():
            pnt = fat_hp_folder.newpoint(name=f"HP-{fat_name}")
            pnt.coords = [(point.geometry.x, point.geometry.y)]
    
    # Download KML
    kml_bytes = BytesIO(kml.kml().encode('utf-8'))
    st.download_button(
        "⬇️ Download KML dengan Struktur Folder",
        kml_bytes.getvalue(),
        "fat_homepass_structured.kml",
        "application/vnd.google-earth.kml+xml"
    )
    
    # Tampilkan statistik
    st.subheader("📊 Statistik FAT AREA")
    
    stats = []
    for _, row in fat_areas.iterrows():
        stats.append({
            'FAT AREA': row['label'],
            'Jumlah HP': row['homepass'],
            'Status': 'Hijau (≥16 HP)' if row['color'] == 'green' else 'Merah (<16 HP)',
            'Luas (m²)': round(row.geometry.area, 2),
            'Bentuk': 'Horizontal' if row.geometry.bounds[3]-row.geometry.bounds[1] < row.geometry.bounds[2]-row.geometry.bounds[0] else 'Vertikal'
        })
    
    st.dataframe(pd.DataFrame(stats))
