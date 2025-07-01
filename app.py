import pandas as pd
from sklearn.cluster import DBSCAN
import geopandas as gpd
from shapely.geometry import Point, MultiPoint, Polygon
import simplekml

# Data contoh (gantikan dengan data sebenarnya dari KML)
data = [
    ["MR.XXXX-XX-P001", "FAT A01", "Blok A1/1"],
    ["MR.XXXX-XX-P001", "FAT A01", "Blok A1/2"],
    # ... tambahkan semua data lainnya ...
    ["MR.XXXX-XX-P001", None, "Blok A2/390"]
]

# Konversi ke DataFrame
df = pd.DataFrame(data, columns=["Project", "FAT_Area", "Blok"])

# 1. Identifikasi FAT Area yang sudah ada
existing_fat_areas = df[df['FAT_Area'].notnull()][['FAT_Area', 'Blok']]

# 2. Kelompokkan HP yang belum memiliki FAT Area
unassigned = df[df['FAT_Area'].isnull()]

# 3. Proses pengelompokan dengan DBSCAN (asumsi ada data koordinat)
# Ini contoh pseudocode - Anda perlu menyesuaikan dengan data sebenarnya
def assign_fat_areas(gdf, max_per_fat=16, max_distance=100):
    # Konversi ke UTM untuk perhitungan jarak
    utm_epsg = 32748  # UTM zone 48S
    gdf_utm = gdf.to_crs(epsg=utm_epsg)
    
    # Dapatkan koordinat
    coords = list(zip(gdf_utm.geometry.x, gdf_utm.geometry.y))
    
    # Clustering
    db = DBSCAN(eps=max_distance, min_samples=1).fit(coords)
    gdf_utm['cluster'] = db.labels_
    
    # Assign FAT Area
    fat_id = len(existing_fat_areas['FAT_Area'].unique()) + 1
    fat_zones = []
    
    for cluster_id in gdf_utm['cluster'].unique():
        cluster = gdf_utm[gdf_utm['cluster'] == cluster_id]
        for i in range(0, len(cluster), max_per_fat):
            chunk = cluster.iloc[i:i+max_per_fat]
            chunk['FAT_Area'] = f'FAT A{fat_id:02d}'
            fat_zones.append(chunk)
            fat_id += 1
    
    return pd.concat(fat_zones)

# 4. Gabungkan hasil dengan FAT Area yang sudah ada
final_assignment = pd.concat([
    existing_fat_areas,
    assign_fat_areas(unassigned)
])

# 5. Export ke KML
def create_fat_kml(df, output_file):
    kml = simplekml.Kml()
    
    for fat_area in df['FAT_Area'].unique():
        group = df[df['FAT_Area'] == fat_area]
        
        # Buat convex hull
        points = [Point(xy) for xy in zip(group.geometry.x, group.geometry.y)]
        multipoint = MultiPoint(points)
        hull = multipoint.convex_hull
        
        if hull.geom_type == 'Polygon':
            pol = kml.newpolygon(
                name=fat_area,
                description=f"{len(group)} HP",
                outerboundaryis=list(hull.exterior.coords)
            )
    
    kml.save(output_file)

# Contoh penggunaan (diasumsikan gdf adalah GeoDataFrame dari KML)
# create_fat_kml(final_assignment, "fat_areas.kml")
