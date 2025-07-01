import streamlit as st
import geopandas as gpd
from shapely.geometry import box, Point
import simplekml
import folium
from streamlit_folium import st_folium
from io import BytesIO, StringIO
import tempfile
import os

st.set_page_config(layout="wide")
st.title("📍 Grid Identifikasi Homepass (Max 16 per Area 250m²)")

# Fungsi untuk validasi KML
def is_valid_kml(content):
    return b"<kml" in content[:100].lower() and b"</kml>" in content[-100:].lower()

# Upload file KML
uploaded_file = st.file_uploader("📤 Upload file KML berisi titik Homepass", type=["kml"])

if uploaded_file:
    try:
        # Baca konten file untuk validasi awal
        content = uploaded_file.read()
        
        # Validasi dasar format KML
        if not is_valid_kml(content):
            st.error("❌ Format file tidak valid. Pastikan file adalah KML yang benar.")
            st.stop()
            
        # Simpan ke file sementara karena geopandas membutuhkan path file untuk KML
        with tempfile.NamedTemporaryFile(suffix=".kml", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        
        try:
            # Baca dengan engine pyogrio yang lebih baru
            gdf = gpd.read_file(tmp_path, driver='KML')
            
            # Pastikan ada geometry points
            if len(gdf) == 0 or not all(gdf.geometry.type == 'Point'):
                st.error("❌ File KML tidak mengandung data titik atau format geometry tidak sesuai")
                st.stop()
                
            st.success(f"✅ KML berhasil dimuat! {len(gdf)} titik ditemukan")
            
            # Konversi ke UTM (Indonesia Barat)
            gdf = gdf.to_crs(epsg=32748)
            
            # Buat grid 15.8m x 15.8m (~250m²)
            minx, miny, maxx, maxy = gdf.total_bounds
            grid_size = 15.8
            polygons = []
            
            x = minx
            while x < maxx:
                y = miny
                while y < maxy:
                    polygons.append(box(x, y, x + grid_size, y + grid_size))
                    y += grid_size
                x += grid_size

            grid = gpd.GeoDataFrame(geometry=polygons, crs=gdf.crs)

            # Hitung titik per grid
            joined = gpd.sjoin(grid, gdf, how="left", predicate="contains")
            counts = joined.groupby('index_left').size()
            grid['homepass'] = counts.fillna(0).astype(int)
            grid['color'] = grid['homepass'].apply(lambda x: 'green' if x <= 16 else 'red')

            # Konversi ke WGS84 untuk visualisasi
            grid_wgs = grid.to_crs(epsg=4326)
            gdf_wgs = gdf.to_crs(epsg=4326)

            # Buat peta Folium
            m = folium.Map(location=[gdf_wgs.geometry.y.mean(), gdf_wgs.geometry.x.mean()], zoom_start=18)
            
            # Tambahkan grid
            for _, row in grid_wgs.iterrows():
                color = "#00ff00" if row['color'] == 'green' else "#ff0000"
                folium.GeoJson(
                    row['geometry'],
                    style_function=lambda x, color=color: {
                        "fillColor": color,
                        "color": color,
                        "weight": 1,
                        "fillOpacity": 0.3,
                    },
                    tooltip=f"{row['homepass']} homepass"
                ).add_to(m)
            
            # Tambahkan titik asli
            for _, row in gdf_wgs.iterrows():
                folium.CircleMarker(
                    location=[row.geometry.y, row.geometry.x],
                    radius=2,
                    color="blue",
                    fill=True,
                    fill_color="blue"
                ).add_to(m)

            st.subheader("🗺️ Hasil Grid di Peta")
            st_folium(m, height=600, width=800)

            # Ekspor ke KML
            kml = simplekml.Kml()
            for _, row in grid_wgs.iterrows():
                poly = kml.newpolygon(
                    name=f"{row['homepass']} HP",
                    outerboundaryis=[(x, y) for x, y in row.geometry.exterior.coords]
                )
                poly.style.polystyle.color = simplekml.Color.green if row['color'] == 'green' else simplekml.Color.red
                poly.style.linestyle.color = simplekml.Color.green if row['color'] == 'green' else simplekml.Color.red
                poly.style.linestyle.width = 2

            # Simpan ke buffer
            kml_bytes = BytesIO()
            kml.save(kml_bytes)
            kml_bytes.seek(0)

            st.download_button(
                label="⬇️ Download KML Hasil",
                data=kml_bytes,
                file_name="grid_homepass.kml",
                mime="application/vnd.google-earth.kml+xml"
            )

        finally:
            # Hapus file temp
            os.unlink(tmp_path)

    except Exception as e:
        st.error(f"❌ Gagal memproses file KML: {str(e)}")
        st.error("Pastikan file berformat KML valid dan mengandung data titik.")
