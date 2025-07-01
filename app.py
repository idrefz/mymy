import streamlit as st
import geopandas as gpd
import pandas as pd
from shapely.geometry import box, Point, MultiPolygon, Polygon
import simplekml
from io import BytesIO
import tempfile

st.set_page_config(layout="wide")
st.title("📍 Grid Identifikasi Homepass (Max 16 per Area 250m²)")

def load_kml(uploaded_file):
    """Fungsi untuk memuat file KML"""
    try:
        with tempfile.NamedTemporaryFile(suffix='.kml') as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp.flush()
            gdf = gpd.read_file(tmp.name, driver='KML')
            return gdf[gdf.geometry.type == 'Point']
    except Exception as e:
        st.error(f"Gagal memuat KML: {str(e)}")
        return None

def create_fat_grids(grid_with_hp):
    """Menggabungkan grid menjadi FAT grid berisi 16 HP"""
    fat_grids = []
    current_fat = []
    current_count = 0
    fat_index = 1
    
    # Urutkan grid berdasarkan jumlah HP (descending)
    sorted_grid = grid_with_hp.sort_values('homepass', ascending=False)
    
    for _, row in sorted_grid.iterrows():
        if current_count + row['homepass'] <= 16:
            current_fat.append(row['geometry'])
            current_count += row['homepass']
        else:
            if current_fat:
                # Gabungkan grid menjadi satu polygon
                combined = MultiPolygon(current_fat).convex_hull
                fat_grids.append({
                    'geometry': combined,
                    'homepass': current_count,
                    'label': f'FAT {fat_index}'
                })
                fat_index += 1
                current_fat = [row['geometry']]
                current_count = row['homepass']
    
    # Tambahkan sisa grid terakhir
    if current_fat:
        combined = MultiPolygon(current_fat).convex_hull
        fat_grids.append({
            'geometry': combined,
            'homepass': current_count,
            'label': f'FAT {fat_index}'
        })
    
    return gpd.GeoDataFrame(fat_grids, crs=grid_with_hp.crs)

# Upload file KML
uploaded_file = st.file_uploader("📤 Upload file KML berisi titik Homepass", type=["kml"])

if uploaded_file:
    # Memuat data KML
    gdf = load_kml(uploaded_file)
    
    if gdf is None or len(gdf) == 0:
        st.error("❌ Tidak ada data titik yang valid dalam file KML")
        st.stop()
    
    st.success(f"✅ Berhasil memuat {len(gdf)} titik Homepass")

    # Konversi ke UTM (Zona 48 untuk Indonesia Barat)
    gdf = gdf.to_crs(epsg=32748)

    # Buat grid 15.8m x 15.8m (~250m²)
    bounds = gdf.total_bounds
    grid_size = 15.8
    polygons = []
    
    x = bounds[0]
    while x < bounds[2]:
        y = bounds[1]
        while y < bounds[3]:
            polygons.append(box(x, y, x + grid_size, y + grid_size))
            y += grid_size
        x += grid_size

    grid = gpd.GeoDataFrame(geometry=polygons, crs=gdf.crs)

    # Hitung titik per grid
    joined = gpd.sjoin(grid, gdf, how='left', predicate='contains')
    counts = joined.groupby(joined.index).size()
    grid['homepass'] = counts.reindex(grid.index, fill_value=0).astype(int)
    
    # Filter hanya grid yang ada HP-nya
    grid_with_hp = grid[grid['homepass'] > 0].copy()
    
    if len(grid_with_hp) == 0:
        st.error("❌ Tidak ada titik Homepass yang masuk dalam grid manapun")
        st.stop()
    
    # Buat FAT grid (gabungkan grid yang <16 HP)
    fat_grids = create_fat_grids(grid_with_hp)
    
    # Konversi ke WGS84 untuk KML
    fat_grids_wgs = fat_grids.to_crs(epsg=4326)

    # Ekspor hasil ke KML
    kml = simplekml.Kml()
    
    for _, row in fat_grids_wgs.iterrows():
        poly = kml.newpolygon(name=f"{row['label']} - {row['homepass']} HP")
        # Konversi geometry ke format yang sesuai
        if isinstance(row.geometry, MultiPolygon):
            for geom in row.geometry.geoms:
                poly.outerboundaryis = [(x,y) for x,y in geom.exterior.coords]
        else:
            poly.outerboundaryis = [(x,y) for x,y in row.geometry.exterior.coords]
        
        poly.style.polystyle.color = simplekml.Color.green
        poly.style.linestyle.color = simplekml.Color.green
        poly.style.linestyle.width = 2

    # Simpan ke buffer
    kml_str = kml.kml()
    kml_bytes = BytesIO(kml_str.encode('utf-8'))
    
    # Tombol download
    st.download_button(
        "⬇️ Download FAT Grid KML",
        kml_bytes.getvalue(),
        "fat_grid_homepass.kml",
        "application/vnd.google-earth.kml+xml"
    )
    
    # Tampilkan statistik
    st.subheader("📊 Statistik FAT Grid")
    st.write(f"Total FAT Grid: {len(fat_grids)}")
    
    # Tabel detail FAT Grid
    fat_stats = []
    for _, row in fat_grids.iterrows():
        fat_stats.append({
            'FAT Grid': row['label'],
            'Jumlah HP': row['homepass'],
            'Luas (m²)': round(row.geometry.area, 2)
        })
    
    st.table(pd.DataFrame(fat_stats))
