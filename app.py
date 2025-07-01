import streamlit as st
import geopandas as gpd
from shapely.geometry import box, Point
import simplekml
import folium
from streamlit_folium import st_folium
from io import BytesIO
import tempfile
import os
from pykml import parser
from lxml import etree

st.set_page_config(layout="wide")
st.title("📍 Grid Identifikasi Homepass (Max 16 per Area 250m²)")

def parse_kml_to_gdf(uploaded_file):
    """Fungsi khusus untuk parsing KML ke GeoDataFrame"""
    try:
        # Coba baca dengan geopandas dulu
        with tempfile.NamedTemporaryFile(suffix='.kml') as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp.flush()
            try:
                return gpd.read_file(tmp.name, driver='KML')
            except:
                # Jika gagal, gunakan pykml sebagai fallback
                uploaded_file.seek(0)
                doc = parser.parse(uploaded_file).getroot()
                points = []
                for pm in doc.findall('.//{http://www.opengis.net/kml/2.2}Placemark'):
                    point = pm.Point
                    if point is not None:
                        coords = point.coordinates.text.strip().split(',')
                        points.append(Point(float(coords[0]), float(coords[1])))
                return gpd.GeoDataFrame(geometry=points, crs="EPSG:4326")
    except Exception as e:
        st.error(f"Gagal parsing KML: {str(e)}")
        return None

# Upload file KML
uploaded_file = st.file_uploader("📤 Upload file KML berisi titik Homepass", type=["kml"])

if uploaded_file:
    # Langsung baca file ke memory
    content = uploaded_file.read()
    
    # Validasi dasar
    if b"<kml" not in content[:100].lower():
        st.error("❌ File bukan format KML yang valid")
        st.stop()
    
    # Reset pointer file
    uploaded_file.seek(0)
    
    # Parsing KML
    gdf = parse_kml_to_gdf(uploaded_file)
    
    if gdf is None or len(gdf) == 0:
        st.error("❌ Tidak ada data titik yang ditemukan dalam KML")
        st.stop()
    
    st.success(f"✅ Berhasil memuat {len(gdf)} titik Homepass")

    # Konversi ke UTM (Zona 48 untuk Indonesia Barat)
    gdf = gdf.to_crs(epsg=32748)

    # Buat grid 15.8m x 15.8m
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
    joined = gpd.sjoin(grid, gdf, how="left", predicate="contains")
    counts = joined.groupby('index_left').size()
    grid['jumlah'] = counts.fillna(0).astype(int)
    grid['warna'] = grid['jumlah'].apply(lambda x: 'green' if x <= 16 else 'red')

    # Visualisasi
    grid_wgs = grid.to_crs(epsg=4326)
    m = folium.Map(location=[grid_wgs.geometry.centroid.y.mean(), 
                           grid_wgs.geometry.centroid.x.mean()], zoom_start=18)
    
    for _, row in grid_wgs.iterrows():
        folium.GeoJson(
            row.geometry,
            style_function=lambda x, c=row['warna']: {
                "fillColor": c,
                "color": c,
                "weight": 1,
                "fillOpacity": 0.4
            },
            tooltip=f"{row['jumlah']} titik"
        ).add_to(m)

    st_folium(m, height=600, width=800)

    # Ekspor hasil
    kml = simplekml.Kml()
    for _, row in grid_wgs.iterrows():
        pol = kml.newpolygon(name=f"{row['jumlah']} titik")
        pol.outerboundaryis = [(x,y) for x,y in row.geometry.exterior.coords]
        pol.style.polystyle.color = simplekml.Color.green if row['warna'] == 'green' else simplekml.Color.red
    
    bio = BytesIO()
    bio.write(kml.kml().encode('utf-8'))
    bio.seek(0)
    
    st.download_button(
        "⬇️ Download Grid KML",
        bio,
        "grid_homepass.kml",
        "application/vnd.google-earth.kml+xml"
    )
