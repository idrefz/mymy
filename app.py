import streamlit as st
import geopandas as gpd
from shapely.geometry import box
import simplekml
import folium
from streamlit_folium import st_folium
from io import BytesIO
import zipfile
import os

st.set_page_config(layout="wide")
st.title("📍 Grid Identifikasi Homepass (Max 16 per Area 250m²)")

# Upload file KML
uploaded_file = st.file_uploader("📤 Upload file KML berisi titik Homepass", type=["kml"])

if uploaded_file:
    try:
        # Read KML directly from memory
        gdf = gpd.read_file(uploaded_file, driver='KML')
        
        # Check if the file contains any data
        if len(gdf) == 0:
            st.error("❌ File KML tidak mengandung data titik")
            st.stop()
            
        st.success(f"✅ KML berhasil dimuat! {len(gdf)} titik ditemukan")

        # Konversi ke UTM (zonasi otomatis)
        gdf = gdf.to_crs(epsg=32748)  # Indonesia Barat

        # Buat grid 15.8m x 15.8m (~250m²)
        minx, miny, maxx, maxy = gdf.total_bounds
        grid_size = 15.8
        polygons = []
        while minx < maxx:
            y = miny
            while y < maxy:
                polygons.append(box(minx, y, minx + grid_size, y + grid_size))
                y += grid_size
            minx += grid_size

        grid = gpd.GeoDataFrame(geometry=polygons, crs=gdf.crs)

        # Spatial join → hitung jumlah titik per grid
        joined = gpd.sjoin(grid, gdf, how="left", predicate="contains")
        counts = joined.groupby('index_left').size()
        grid['homepass'] = counts.fillna(0).astype(int)

        # Tambah warna
        grid['color'] = grid['homepass'].apply(lambda x: 'green' if x <= 16 else 'red')

        # Tampilkan ke peta interaktif
        grid_wgs = grid.to_crs(epsg=4326)
        gdf_wgs = gdf.to_crs(epsg=4326)

        m = folium.Map(location=[gdf_wgs.geometry.y.mean(), gdf_wgs.geometry.x.mean()], zoom_start=18)
        for _, row in grid_wgs.iterrows():
            sim_color = "#00ff00" if row['color'] == 'green' else "#ff0000"
            folium.GeoJson(
                row['geometry'],
                style_function=lambda x, color=sim_color: {
                    "fillColor": color,
                    "color": color,
                    "weight": 1,
                    "fillOpacity": 0.3,
                },
                tooltip=f"{row['homepass']} homepass"
            ).add_to(m)

        for _, row in gdf_wgs.iterrows():
            folium.CircleMarker(location=[row.geometry.y, row.geometry.x], radius=2, color="blue").add_to(m)

        st.subheader("🗺️ Hasil Grid di Peta")
        st_folium(m, height=600)

        # Export ke KML
        kml = simplekml.Kml()
        for _, row in grid.to_crs(epsg=4326).iterrows():
            poly = kml.newpolygon(name=f"{row['homepass']} HP",
                                  outerboundaryis=[(x, y) for x, y in row.geometry.exterior.coords])
            kml_color = 'ff00ff00' if row['color'] == 'green' else 'ff0000ff'
            poly.style.polystyle.color = kml_color
            poly.style.linestyle.width = 1

        kml_io = BytesIO()
        kml.save(kml_io)
        kml_bytes = kml_io.getvalue()

        st.download_button("⬇️ Download KML Hasil", kml_bytes, "grid_homepass.kml")

    except Exception as e:
        st.error(f"❌ Gagal memproses file KML: {str(e)}")
        st.error("Pastikan file KML berformat benar dan mengandung data titik")
