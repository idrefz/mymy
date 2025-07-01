import streamlit as st
import geopandas as gpd
import pandas as pd
from shapely.geometry import box, Point
import simplekml
import folium
from streamlit_folium import st_folium
from io import BytesIO
import tempfile
import os

st.set_page_config(layout="wide")
st.title("📍 Grid Identifikasi Homepass (Max 16 per Area 250m²)")

def load_kml(uploaded_file):
    """Fungsi untuk memuat file KML dengan berbagai metode"""
    try:
        # Coba baca langsung dengan geopandas
        with tempfile.NamedTemporaryFile(suffix='.kml') as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp.flush()
            gdf = gpd.read_file(tmp.name, driver='KML')
            return gdf[gdf.geometry.type == 'Point']  # Filter hanya titik
    
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

    # Hitung titik per grid dengan metode yang lebih robust
    grid['homepass'] = 0  # Inisialisasi
    
    # Spatial join
    joined = gpd.sjoin(grid, gdf, how='left', predicate='contains')
    
    if not joined.empty:
        # Cara 1: Group by index grid yang asli
        counts = joined.groupby(joined.index).size()
        grid['homepass'] = counts.reindex(grid.index, fill_value=0).astype(int)
        
        # Cara alternatif 2:
        # grid['homepass'] = grid.geometry.apply(
        #     lambda g: sum(gdf.geometry.within(g))
    
    # Tambah warna
    grid['color'] = grid['homepass'].apply(
        lambda x: 'green' if x <= 16 else 'red')

    # Konversi ke WGS84 untuk visualisasi
    grid_wgs = grid.to_crs(epsg=4326)
    gdf_wgs = gdf.to_crs(epsg=4326)

    # Buat peta Folium
    m = folium.Map(
        location=[gdf_wgs.geometry.y.mean(), gdf_wgs.geometry.x.mean()], 
        zoom_start=18,
        control_scale=True
    )
    
    # Tambahkan grid ke peta
    for _, row in grid_wgs.iterrows():
        folium.GeoJson(
            row.geometry,
            style_function=lambda x, color=row['color']: {
                "fillColor": color,
                "color": color,
                "weight": 1,
                "fillOpacity": 0.4
            },
            tooltip=f"{row['homepass']} titik"
        ).add_to(m)
    
    # Tambahkan titik asli
    for _, row in gdf_wgs.iterrows():
        folium.CircleMarker(
            location=[row.geometry.y, row.geometry.x],
            radius=3,
            color='blue',
            fill=True,
            fill_color='blue',
            fill_opacity=0.7
        ).add_to(m)

    # Tambahkan legenda
    folium.LayerControl().add_to(m)
    
    st.subheader("🗺️ Peta Distribusi Homepass")
    st_folium(m, height=600, width=800)

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

    # Simpan ke buffer
    kml_bytes = BytesIO()
    kml.save(kml_bytes)
    kml_bytes.seek(0)
    
    st.download_button(
        "⬇️ Download Grid KML",
        kml_bytes,
        "grid_homepass.kml",
        "application/vnd.google-earth.kml+xml"
    )

    # Tampilkan statistik
    st.subheader("📊 Statistik")
    col1, col2 = st.columns(2)
    
    with col1:
        st.metric("Total Titik Homepass", len(gdf))
        st.metric("Total Grid", len(grid))
    
    with col2:
        st.metric("Grid Hijau (≤16 titik)", len(grid[grid['color'] == 'green']))
        st.metric("Grid Merah (>16 titik)", len(grid[grid['color'] == 'red']))
