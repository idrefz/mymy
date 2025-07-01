import simplekml
from shapely.geometry import Point, MultiPoint, Polygon
import pandas as pd
import numpy as np
from sklearn.cluster import DBSCAN
import geopandas as gpd
from io import BytesIO
import tempfile
import os

def load_kml_data(uploaded_file):
    """Membaca data KML dan mengembalikan GeoDataFrame"""
    try:
        with tempfile.NamedTemporaryFile(suffix='.kml', delete=False) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name
        
        gdf = gpd.read_file(tmp_path, driver='KML')
        os.unlink(tmp_path)
        
        # Ekstrak semua titik (handle Point dan LineString)
        all_points = []
        blok_names = []
        
        for idx, geom in enumerate(gdf.geometry):
            if geom.geom_type == 'Point':
                all_points.append(geom)
                blok_names.append(gdf.iloc[idx].get('Name', f'HP-{idx}'))
            elif geom.geom_type == 'LineString':
                for coord in geom.coords:
                    all_points.append(Point(coord))
                    blok_names.append(f'Line-{idx}-{len(blok_names)}')
        
        points_gdf = gpd.GeoDataFrame({'Blok': blok_names}, geometry=all_points, crs=gdf.crs)
        return points_gdf
    
    except Exception as e:
        print(f"Error loading KML: {str(e)}")
        return None

def cluster_homepass(gdf, max_distance=100, max_per_fat=16):
    """Mengelompokkan HomePass ke dalam FAT Areas"""
    # Konversi ke UTM untuk perhitungan jarak akurat
    utm_epsg = 32748  # UTM zone 48S (Indonesia Barat)
    gdf_utm = gdf.to_crs(epsg=utm_epsg)
    
    # Dapatkan koordinat untuk clustering
    gdf_utm['x'] = gdf_utm.geometry.x
    gdf_utm['y'] = gdf_utm.geometry.y
    coords = gdf_utm[['x', 'y']].values
    
    # Lakukan clustering dengan DBSCAN
    db = DBSCAN(eps=max_distance, min_samples=1).fit(coords)
    gdf_utm['cluster'] = db.labels_
    
    # Kembalikan ke WGS84
    gdf_wgs = gdf_utm.to_crs(epsg=4326)
    
    # Assign FAT Area
    fat_zones = []
    fat_id = 1
    
    for cluster_id in gdf_utm['cluster'].unique():
        cluster = gdf_utm[gdf_utm['cluster'] == cluster_id]
        cluster = cluster.sort_values('x')
        
        for i in range(0, len(cluster), max_per_fat):
            chunk = cluster.iloc[i:i+max_per_fat]
            chunk['FAT_Area'] = f'FAT A{fat_id:02d}'
            fat_zones.append(chunk)
            fat_id += 1
    
    fat_areas = pd.concat(fat_zones)
    
    # Tambahkan kolom latitude dan longitude
    fat_areas['longitude'] = fat_areas.geometry.x
    fat_areas['latitude'] = fat_areas.geometry.y
    
    return fat_areas[['FAT_Area', 'Blok', 'latitude', 'longitude']]

def create_structured_kml(fat_areas_df, output_filename):
    """Membuat struktur KML dengan folder terorganisir"""
    kml = simplekml.Kml()
    
    # Folder utama
    main_folder = kml.newfolder(name="FAT Areas Coverage")
    
    # Warna untuk FAT Areas berbeda
    colors = [
        simplekml.Color.blue,
        simplekml.Color.green,
        simplekml.Color.red,
        simplekml.Color.yellow,
        simplekml.Color.orange,
        simplekml.Color.purple
    ]
    
    for i, (fat_name, group) in enumerate(fat_areas_df.groupby('FAT_Area')):
        # Folder untuk setiap FAT Area
        fat_folder = main_folder.newfolder(name=fat_name)
        
        # 1. Buat boundary polygon
        points = [Point(lon, lat) for lon, lat in zip(group['longitude'], group['latitude'])]
        multipoint = MultiPoint(points)
        hull = multipoint.convex_hull
        
        if hull.geom_type == 'Polygon':
            pol = fat_folder.newpolygon(
                name=f"{fat_name} Boundary",
                description=f"Total {len(group)} HomePass",
                outerboundaryis=list(hull.exterior.coords)
            )
            color = colors[i % len(colors)]
            pol.style.polystyle.color = simplekml.Color.changealphaint(50, color)
            pol.style.linestyle.color = color
            pol.style.linestyle.width = 2
        
        # 2. Folder untuk HomePass
        hp_folder = fat_folder.newfolder(name="HomePass")
        
        # Sub-folder berdasarkan tipe (contoh: HH, HI, dll)
        hh_folder = hp_folder.newfolder(name="HH")
        
        for _, row in group.iterrows():
            # Point untuk setiap HomePass
            pnt = hh_folder.newpoint(
                name=row['Blok'],
                coords=[(row['longitude'], row['latitude'])],
                description=f"FAT Area: {fat_name}"
            )
            pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/pal4/icon28.png'
            pnt.style.labelstyle.scale = 0.8  # Ukuran label
    
    kml.save(output_filename)

def main():
    import streamlit as st
    
    st.title("FAT Area dan HomePass Organizer")
    st.markdown("""
    Aplikasi untuk mengelompokkan HomePass ke dalam FAT Areas dengan struktur folder KML.
    """)
    
    # Upload file
    uploaded_file = st.file_uploader("Upload file KML berisi HomePass", type=['kml'])
    
    if uploaded_file is not None:
        # Parameter pengelompokan
        col1, col2 = st.columns(2)
        with col1:
            max_hp = st.slider("Maksimal HP per FAT area", 1, 20, 16)
        with col2:
            max_dist = st.slider("Jarak maksimal dalam cluster (meter)", 50, 200, 100)
        
        if st.button("Proses Pengelompokan FAT"):
            with st.spinner('Memproses data...'):
                try:
                    # 1. Load data
                    gdf = load_kml_data(uploaded_file)
                    if gdf is None:
                        st.error("Gagal memuat file KML")
                        return
                    
                    # 2. Cluster HomePass
                    fat_areas_df = cluster_homepass(gdf, max_dist, max_hp)
                    
                    # 3. Buat KML terstruktur
                    with tempfile.NamedTemporaryFile(suffix='.kml', delete=False) as tmp:
                        create_structured_kml(fat_areas_df, tmp.name)
                        with open(tmp.name, 'rb') as f:
                            kml_bytes = f.read()
                    
                    # 4. Download hasil
                    st.success("Proses selesai!")
                    st.download_button(
                        label="Download Structured FAT Areas KML",
                        data=kml_bytes,
                        file_name="fat_areas_structured.kml",
                        mime="application/vnd.google-earth.kml+xml"
                    )
                    
                    # Tampilkan preview
                    st.subheader("Preview Data")
                    st.write(fat_areas_df.head())
                    
                except Exception as e:
                    st.error(f"Error: {str(e)}")

if __name__ == "__main__":
    main()
