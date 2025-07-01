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
    """Membaca data KML dan mempertahankan koordinat asli"""
    try:
        with tempfile.NamedTemporaryFile(suffix='.kml', delete=False) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name
        
        gdf = gpd.read_file(tmp_path, driver='KML')
        os.unlink(tmp_path)
        
        # Ekstrak semua titik dengan koordinat asli
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
        
        # Simpan dalam GeoDataFrame dengan CRS asli (WGS84)
        points_gdf = gpd.GeoDataFrame({'Blok': blok_names}, geometry=all_points, crs='EPSG:4326')
        
        # Tambahkan kolom longitude dan latitude asli
        points_gdf['longitude'] = points_gdf.geometry.x
        points_gdf['latitude'] = points_gdf.geometry.y
        
        return points_gdf
    
    except Exception as e:
        print(f"Error loading KML: {str(e)}")
        return None

def cluster_homepass(gdf, max_distance=100, max_per_fat=16):
    """Mengelompokkan HomePass tanpa mengubah koordinat asli"""
    # Buat salinan data asli
    original_coords = gdf[['longitude', 'latitude']].values
    
    # Untuk clustering, konversi ke meter (UTM)
    utm_epsg = 32748  # UTM zone 48S (Indonesia Barat)
    gdf_utm = gdf.to_crs(epsg=utm_epsg)
    
    # Dapatkan koordinat UTM untuk clustering
    coords_utm = np.array([(geom.x, geom.y) for geom in gdf_utm.geometry])
    
    # Lakukan clustering dengan DBSCAN
    db = DBSCAN(eps=max_distance, min_samples=1).fit(coords_utm)
    gdf['cluster'] = db.labels_
    
    # Assign FAT Area menggunakan koordinat asli
    fat_zones = []
    fat_id = 1
    
    for cluster_id in gdf['cluster'].unique():
        cluster = gdf[gdf['cluster'] == cluster_id]
        cluster = cluster.sort_values('longitude')  # Urutkan berdasarkan longitude
        
        for i in range(0, len(cluster), max_per_fat):
            chunk = cluster.iloc[i:i+max_per_fat].copy()
            chunk['FAT_Area'] = f'FAT A{fat_id:02d}'
            fat_zones.append(chunk)
            fat_id += 1
    
    fat_areas = pd.concat(fat_zones)
    return fat_areas[['FAT_Area', 'Blok', 'longitude', 'latitude', 'geometry']]

def create_structured_kml(fat_areas_df, output_filename):
    """Membuat KML dengan koordinat asli"""
    kml = simplekml.Kml()
    
    main_folder = kml.newfolder(name="FAT Areas Coverage")
    
    for i, (fat_name, group) in enumerate(fat_areas_df.groupby('FAT_Area')):
        fat_folder = main_folder.newfolder(name=fat_name)
        
        # Gunakan geometry asli untuk polygon boundary
        multipoint = MultiPoint(group.geometry.tolist())
        hull = multipoint.convex_hull
        
        if hull.geom_type == 'Polygon':
            pol = fat_folder.newpolygon(
                name=f"{fat_name} Boundary",
                description=f"Total {len(group)} HomePass",
                outerboundaryis=[(p.x, p.y) for p in hull.exterior.coords]
            )
            pol.style.polystyle.color = simplekml.Color.changealphaint(50, simplekml.Color.green)
        
        # Folder HomePass
        hp_folder = fat_folder.newfolder(name="HomePass")
        hh_folder = hp_folder.newfolder(name="HH")
        
        for _, row in group.iterrows():
            pnt = hh_folder.newpoint(
                name=row['Blok'],
                coords=[(row['longitude'], row['latitude'])],
                description=f"FAT Area: {fat_name}"
            )
            pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/pal4/icon28.png'
    
    kml.save(output_filename)

def main():
    import streamlit as st
    
    st.title("FAT Area Organizer (Preserve Coordinates)")
    st.markdown("""
    Aplikasi untuk mengelompokkan HomePass ke FAT Areas **tanpa mengubah koordinat asli**.
    """)
    
    uploaded_file = st.file_uploader("Upload file KML", type=['kml'])
    
    if uploaded_file is not None:
        col1, col2 = st.columns(2)
        with col1:
            max_hp = st.number_input("Maks HP per FAT", 1, 50, 16)
        with col2:
            max_dist = st.number_input("Jarak cluster (meter)", 50, 500, 100)
        
        if st.button("Proses"):
            with st.spinner('Memproses...'):
                try:
                    # 1. Load data dengan koordinat asli
                    gdf = load_kml_data(uploaded_file)
                    if gdf is None:
                        st.error("Gagal memuat file")
                        return
                    
                    # 2. Cluster tanpa ubah koordinat
                    fat_areas = cluster_homepass(gdf, max_dist, max_hp)
                    
                    # 3. Buat KML
                    with tempfile.NamedTemporaryFile(suffix='.kml', delete=False) as tmp:
                        create_structured_kml(fat_areas, tmp.name)
                        with open(tmp.name, 'rb') as f:
                            kml_bytes = f.read()
                    
                    st.success("Selesai! Koordinat asli tetap dipertahankan")
                    st.download_button(
                        label="Download KML",
                        data=kml_bytes,
                        file_name="fat_areas_preserved_coords.kml",
                        mime="application/vnd.google-earth.kml+xml"
                    )
                    
                    # Tampilkan koordinat asli
                    st.subheader("Data Koordinat Asli")
                    st.dataframe(fat_areas[['Blok', 'longitude', 'latitude']].head())
                    
                except Exception as e:
                    st.error(f"Error: {str(e)}")

if __name__ == "__main__":
    main()
