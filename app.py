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

def create_fat_areas(grid_with_hp, gdf):
    """Hanya membuat FAT area untuk grid yang memiliki HP"""
    fat_areas = []
    homepass_groups = {}
    fat_index = 1
    
    # Urutkan berdasarkan jumlah HP (descending)
    grid_sorted = grid_with_hp.sort_values('homepass', ascending=False)
    
    for _, row in grid_sorted.iterrows():
        if row['homepass'] == 0:
            continue  # Skip grid tanpa HP
            
        if row['homepass'] >= 16:
            # Grid dengan ≥16 HP menjadi FAT area sendiri
            fat_areas.append({
                'geometry': row['geometry'],
                'homepass': row['homepass'],
                'label': f'FAT {fat_index}',
                'color': 'green'
            })
            
            # Kelompokkan HP
            points_in_grid = gdf[gdf.geometry.within(row['geometry'])]
            homepass_groups[f'FAT {fat_index}'] = points_in_grid
            fat_index += 1
        else:
            # Cari FAT area terdekat yang masih bisa menampung
            added = False
            for fat in fat_areas:
                if fat['homepass'] + row['homepass'] <= 16:
                    # Gabungkan geometry
                    fat['geometry'] = MultiPolygon([fat['geometry'], row['geometry']]).convex_hull
                    fat['homepass'] += row['homepass']
                    
                    # Gabungkan HP
                    points_in_grid = gdf[gdf.geometry.within(row['geometry'])]
                    if fat['label'] in homepass_groups:
                        homepass_groups[fat['label']] = pd.concat([homepass_groups[fat['label']], points_in_grid])
                    else:
                        homepass_groups[fat['label']] = points_in_grid
                    
                    added = True
                    break
            
            if not added:
                # Buat FAT area baru untuk grid ini
                fat_areas.append({
                    'geometry': row['geometry'],
                    'homepass': row['homepass'],
                    'label': f'FAT {fat_index}',
                    'color': 'red'  # Warna merah karena <16 HP
                })
                
                points_in_grid = gdf[gdf.geometry.within(row['geometry'])]
                homepass_groups[f'FAT {fat_index}'] = points_in_grid
                fat_index += 1
    
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
    
    # Filter hanya grid dengan HP
    grid_with_hp = grid[grid['homepass'] > 0].copy()
    
    if len(grid_with_hp) == 0:
        st.error("❌ Tidak ada titik Homepass yang masuk dalam grid manapun")
        st.stop()
    
    # Buat FAT area hanya untuk grid dengan HP
    fat_areas, homepass_groups = create_fat_areas(grid_with_hp, gdf)
    fat_areas_wgs = fat_areas.to_crs(epsg=4326)
    
    # Buat KML dengan struktur folder
    kml = simplekml.Kml()
    
    # Folder FAT AREA (hanya yang ada HP-nya)
    if len(fat_areas) > 0:
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
    
    # Folder HOMEPASS (hanya untuk FAT area yang ada)
    if len(homepass_groups) > 0:
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
    
    # Tampilkan statistik hanya untuk FAT area yang ada
    st.subheader("📊 Statistik FAT AREA")
    
    if len(fat_areas) > 0:
        stats = []
        for _, row in fat_areas.iterrows():
            stats.append({
                'FAT AREA': row['label'],
                'Jumlah HP': row['homepass'],
                'Status': 'Hijau (≥16 HP)' if row['color'] == 'green' else 'Merah (<16 HP)',
                'Luas (m²)': round(row.geometry.area, 2)
            })
        
        st.dataframe(pd.DataFrame(stats))
    else:
        st.info("Tidak ada FAT AREA yang teridentifikasi")
