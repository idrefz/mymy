import streamlit as st
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, MultiPoint, Polygon
import simplekml
from io import BytesIO
import tempfile
import os

st.title('Pengelompokan FAT Area dari KML')

# Fungsi untuk membaca KML dengan fallback
def read_kml(file):
    try:
        # Coba baca dengan geopandas biasa
        return gpd.read_file(file, driver='KML')
    except Exception as e:
        st.warning(f"Gagal baca dengan pyogrio: {str(e)}. Mencoba metode alternatif...")
        try:
            # Simpan ke file sementara dan baca kembali
            with tempfile.NamedTemporaryFile(suffix='.kml', delete=False) as tmp:
                tmp.write(file.getvalue())
                tmp_path = tmp.name
            
            gdf = gpd.read_file(tmp_path, driver='KML')
            os.unlink(tmp_path)
            return gdf
        except Exception as e:
            st.error(f"Gagal membaca file KML: {str(e)}")
            return None

# Upload file
uploaded_file = st.file_uploader("Upload file KML berisi HomePass", type=['kml'])

if uploaded_file is not None:
    # Baca file KML
    gdf = read_kml(uploaded_file)
    
    if gdf is not None and not gdf.empty:
        st.success(f"Berhasil memuat {len(gdf)} fitur")
        
        # Tampilkan preview data
        st.subheader("Preview Data")
        st.write(gdf.head())
        
        # Ekstrak semua titik (handle Point dan LineString)
        all_points = []
        for geom in gdf.geometry:
            if geom.geom_type == 'Point':
                all_points.append(geom)
            elif geom.geom_type == 'LineString':
                for coord in geom.coords:
                    all_points.append(Point(coord))
        
        if not all_points:
            st.error("Tidak ditemukan titik/garis yang valid dalam KML")
        else:
            points_gdf = gpd.GeoDataFrame(geometry=all_points, crs=gdf.crs)
            
            # Konversi ke UTM untuk perhitungan jarak akurat
            utm_epsg = 32748  # UTM zone 48S (Indonesia Barat)
            points_utm = points_gdf.to_crs(epsg=utm_epsg)
            
            # Proses clustering dan pembuatan FAT area
            max_hp = st.slider("Maksimal HP per FAT area", 1, 20, 16)
            max_dist = st.slider("Jarak maksimal dalam cluster (meter)", 50, 200, 100)
            
            if st.button("Proses Pengelompokan FAT"):
                with st.spinner('Sedang memproses...'):
                    try:
                        # Dapatkan koordinat untuk clustering
                        points_utm['x'] = points_utm.geometry.x
                        points_utm['y'] = points_utm.geometry.y
                        coords = points_utm[['x', 'y']].values
                        
                        # Lakukan clustering
                        db = DBSCAN(eps=max_dist, min_samples=1).fit(coords)
                        points_utm['cluster'] = db.labels_
                        
                        # Kembalikan ke WGS84
                        points_wgs = points_utm.to_crs(epsg=4326)
                        
                        # Buat FAT area
                        fat_zones = []
                        fat_id = 1
                        
                        for cid in points_utm['cluster'].unique():
                            cluster = points_utm[points_utm['cluster'] == cid]
                            cluster = cluster.sort_values('x')
                            
                            for i in range(0, len(cluster), max_hp):
                                chunk = cluster.iloc[i:i+max_hp]
                                chunk['fat'] = f'FAT A{fat_id:02d}'
                                fat_zones.append(chunk)
                                fat_id += 1
                        
                        fat_areas = pd.concat(fat_zones)
                        
                        # Buat polygon convex hull
                        kml = simplekml.Kml()
                        for fat in fat_areas['fat'].unique():
                            group = fat_areas[fat_areas['fat'] == fat]
                            multipoint = MultiPoint(group.geometry.tolist())
                            hull = multipoint.convex_hull
                            
                            if hull.geom_type == 'Polygon':
                                pol = kml.newpolygon(
                                    name=fat,
                                    description=f"{len(group)} HP",
                                    outerboundaryis=[(p.x, p.y) for p in hull.exterior.coords]
                                )
                                pol.style.polystyle.color = simplekml.Color.changealphaint(50, simplekml.Color.green)
                        
                        # Simpan ke bytes untuk download
                        kml_bytes = BytesIO()
                        kml.save(kml_bytes)
                        kml_bytes.seek(0)
                        
                        st.success("Proses selesai!")
                        st.download_button(
                            label="Download FAT Areas KML",
                            data=kml_bytes,
                            file_name="fat_areas.kml",
                            mime="application/vnd.google-earth.kml+xml"
                        )
                        
                    except Exception as e:
                        st.error(f"Error saat pemrosesan: {str(e)}")
