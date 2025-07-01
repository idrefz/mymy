import streamlit as st
import geopandas as gpd
import pandas as pd
from shapely.geometry import box, Point
import simplekml
from io import BytesIO, StringIO
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
    grid['homepass'] = 0
    
    joined = gpd.sjoin(grid, gdf, how='left', predicate='contains')
    
    if not joined.empty:
        counts = joined.groupby(joined.index).size()
        grid['homepass'] = counts.reindex(grid.index, fill_value=0).astype(int)
    
    # Tambah warna
    grid['color'] = grid['homepass'].apply(
        lambda x: 'green' if x <= 16 else 'red')

    # Konversi ke WGS84 untuk KML
    grid_wgs = grid.to_crs(epsg=4326)

    # Ekspor hasil ke KML
    kml = simplekml.Kml()
    
    for _, row in grid_wgs.iterrows():
        poly = kml.newpolygon(name=f"{row['homepass']} titik")
        poly.outerboundaryis = [(x,y) for x,y in row.geometry.exterior.coords]
        
        if row['color'] == 'green':
            poly.style.polystyle.color = simplekml.Color.green
            poly.style.linestyle.color = simplekml.Color.green
        else:
            poly.style.polystyle.color = simplekml.Color.red
            poly.style.linestyle.color = simplekml.Color.red
        
        poly.style.linestyle.width = 2

    # Perbaikan penyimpanan KML
    try:
        # Simpan ke string dulu
        kml_str = kml.kml()
        
        # Konversi ke bytes
        kml_bytes = BytesIO(kml_str.encode('utf-8'))
        
        # Tombol download
        st.download_button(
            "⬇️ Download Grid KML",
            kml_bytes.getvalue(),
            "grid_homepass.kml",
            "application/vnd.google-earth.kml+xml"
        )
        
        # Tampilkan statistik singkat
        st.write(f"Total Grid: {len(grid)}")
        st.write(f"Grid Hijau (≤16 titik): {len(grid[grid['color'] == 'green'])}")
        st.write(f"Grid Merah (>16 titik): {len(grid[grid['color'] == 'red'])}")
        
    except Exception as e:
        st.error(f"Gagal membuat file KML: {str(e)}")
