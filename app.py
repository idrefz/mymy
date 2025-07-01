import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import box, Point, MultiPolygon, Polygon
import simplekml
from io import BytesIO
import zipfile
import math
from collections import deque

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
    """Membuat grid yang sejajar dengan boundary area"""
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
    
    grid = gpd.GeoDataFrame(geometry=polygons, crs=gdf.crs)
    grid['row'] = grid.geometry.apply(lambda g: int(round(g.centroid.y / grid_size)))
    grid['col'] = grid.geometry.apply(lambda g: int(round(g.centroid.x / grid_size)))
    
    return grid

def find_adjacent_grids(grid, current_idx, visited):
    """Mencari grid yang adjacent (atas, bawah, kiri, kanan)"""
    directions = [(-1,0), (1,0), (0,-1), (0,1)]  # atas, bawah, kiri, kanan
    current = grid.loc[current_idx]
    adjacent = []
    
    for dr, dc in directions:
        adj_row, adj_col = current['row'] + dr, current['col'] + dc
        candidate = grid[(grid['row'] == adj_row) & (grid['col'] == adj_col)]
        
        if not candidate.empty:
            adj_idx = candidate.index[0]
            if adj_idx not in visited and grid.loc[adj_idx]['homepass'] > 0:
                adjacent.append(adj_idx)
    
    return adjacent

def create_optimized_fat_areas(grid_with_hp, gdf):
    """Membuat FAT area dengan penggabungan optimal"""
    fat_areas = []
    homepass_groups = {}
    fat_index = 1
    visited = set()
    
    # Prioritaskan grid dengan HP terbanyak
    sorted_indices = grid_with_hp.sort_values('homepass', ascending=False).index
    
    for idx in sorted_indices:
        if idx in visited or grid_with_hp.loc[idx]['homepass'] == 0:
            continue
        
        # Mulai FAT area baru
        current_fat = [grid_with_hp.loc[idx]['geometry']]
        current_hp = grid_with_hp.loc[idx]['homepass']
        visited.add(idx)
        
        # Cari grid adjacent yang bisa digabung
        queue = deque(find_adjacent_grids(grid_with_hp, idx, visited))
        
        while queue and current_hp < 16:
            adj_idx = queue.popleft()
            
            if adj_idx in visited:
                continue
                
            adj_hp = grid_with_hp.loc[adj_idx]['homepass']
            
            # Cek apakah bisa digabung tanpa melebihi 16 HP
            if current_hp + adj_hp <= 16:
                current_fat.append(grid_with_hp.loc[adj_idx]['geometry'])
                current_hp += adj_hp
                visited.add(adj_idx)
                
                # Tambahkan tetangga baru ke queue
                queue.extend(find_adjacent_grids(grid_with_hp, adj_idx, visited))
        
        # Cek grid terisolir (kurang dari 16 HP tapi tidak ada tetangga)
        if current_hp < 16 and not queue:
            # Cari grid terdekat dalam radius 3 grid
            current_center = grid_with_hp.loc[idx]['geometry'].centroid
            nearby_grids = grid_with_hp[
                (grid_with_hp.geometry.centroid.distance(current_center) <= 3*15.8) & 
                (~grid_with_hp.index.isin(visited)) &
                (grid_with_hp['homepass'] > 0)
            ]
            
            for _, row in nearby_grids.iterrows():
                if current_hp + row['homepass'] <= 16:
                    current_fat.append(row['geometry'])
                    current_hp += row['homepass']
                    visited.add(row.name)
        
        # Buat FAT area
        combined_geom = MultiPolygon(current_fat).convex_hull
        fat_areas.append({
            'geometry': combined_geom,
            'homepass': current_hp,
            'label': f'FAT {fat_index}',
            'color': 'green' if current_hp >= 16 else 'red'
        })
        
        # Kelompokkan Homepass
        points_in_fat = gdf[gdf.geometry.within(combined_geom)]
        homepass_groups[f'FAT {fat_index}'] = points_in_fat
        
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
    
    # Filter grid dengan HP
    grid_with_hp = grid[grid['homepass'] > 0].copy()
    
    if len(grid_with_hp) == 0:
        st.error("❌ Tidak ada titik Homepass yang masuk dalam grid manapun")
        st.stop()
    
    # Buat FAT area yang optimal
    fat_areas, homepass_groups = create_optimized_fat_areas(grid_with_hp, gdf)
    fat_areas_wgs = fat_areas.to_crs(epsg=4326)
    
    # Buat ZIP output
    with BytesIO() as zip_buffer:
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 1. FAT AREA
            kml_fat = simplekml.Kml()
            for _, row in fat_areas_wgs.iterrows():
                poly = kml_fat.newpolygon(name=row['label'])
                poly.style.polystyle.color = simplekml.Color.green if row['color'] == 'green' else simplekml.Color.red
                poly.style.linestyle.color = simplekml.Color.green if row['color'] == 'green' else simplekml.Color.red
                poly.style.linestyle.width = 2
                
                if hasattr(row.geometry, 'geoms'):
                    for geom in row.geometry.geoms:
                        poly.outerboundaryis = [(x,y) for x,y in geom.exterior.coords]
                else:
                    poly.outerboundaryis = [(x,y) for x,y in row.geometry.exterior.coords]
                
                poly.description = f"Jumlah HP: {row['homepass']}"
            
            zipf.writestr("FAT AREA/fat_areas.kml", kml_fat.kml())
            
            # 2. HOMEPASS per FAT AREA
            for fat_name, points in homepass_groups.items():
                kml_hp = simplekml.Kml()
                points_wgs = points.to_crs(epsg=4326)
                
                for _, point in points_wgs.iterrows():
                    pnt = kml_hp.newpoint(name=f"HP-{fat_name}")
                    pnt.coords = [(point.geometry.x, point.geometry.y)]
                
                zipf.writestr(f"HOMEPASS/{fat_name}/homepass.kml", kml_hp.kml())
        
        # Download button
        st.download_button(
            "⬇️ Download All Data (ZIP)",
            zip_buffer.getvalue(),
            "fat_homepass_data.zip",
            "application/zip"
        )
    
    # Tampilkan statistik
    st.subheader("📊 Statistik FAT AREA")
    
    stats = []
    for _, row in fat_areas.iterrows():
        bounds = row.geometry.bounds
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        
        stats.append({
            'FAT AREA': row['label'],
            'Jumlah HP': row['homepass'],
            'Status': 'Hijau (≥16 HP)' if row['color'] == 'green' else 'Merah (<16 HP)',
            'Luas (m²)': round(row.geometry.area, 2),
            'Lebar (m)': round(width, 1),
            'Tinggi (m)': round(height, 1),
            'Grid Terpakai': len(homepass_groups[row['label']])
        })
    
    st.dataframe(pd.DataFrame(stats))
