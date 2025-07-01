import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPoint, Point, LineString
from sklearn.cluster import DBSCAN
import simplekml
import numpy as np
from pyproj import CRS, Transformer

def extract_points_from_linestring(linestring):
    """Ekstrak titik-titik dari LineString"""
    return [Point(xy) for xy in linestring.coords]

def load_and_prepare_data(input_kml):
    """Muat data KML dan ekstrak semua titik"""
    gdf = gpd.read_file(input_kml, driver='KML')
    
    # Ekstrak semua titik (handle baik Point maupun LineString)
    points = []
    for geom in gdf.geometry:
        if geom.geom_type == 'Point':
            points.append(geom)
        elif geom.geom_type == 'LineString':
            points.extend(extract_points_from_linestring(geom))
    
    # Buat GeoDataFrame baru dari titik-titik
    points_gdf = gpd.GeoDataFrame(geometry=points, crs=gdf.crs)
    return points_gdf

def cluster_points(points_gdf, max_distance_m=100):
    """Kelompokkan titik menggunakan DBSCAN"""
    # Konversi ke UTM untuk perhitungan jarak akurat
    utm_epsg = 32748  # UTM zone 48S (untuk Indonesia Barat)
    points_utm = points_gdf.to_crs(epsg=utm_epsg)
    
    # Dapatkan koordinat untuk clustering
    points_utm['x'] = points_utm.geometry.x
    points_utm['y'] = points_utm.geometry.y
    coords = points_utm[['x', 'y']].values
    
    # Lakukan clustering dengan DBSCAN
    db = DBSCAN(eps=max_distance_m, min_samples=1).fit(coords)
    points_utm['cluster'] = db.labels_
    
    # Kembalikan ke WGS84
    points_utm = points_utm.to_crs(epsg=4326)
    return points_utm

def create_fat_areas(clustered_points, max_hp_per_fat=16):
    """Buat area FAT dengan maksimal 16 HP per area"""
    fat_zones = []
    fat_id = 1
    
    for cluster_id in clustered_points['cluster'].unique():
        cluster_points = clustered_points[clustered_points['cluster'] == cluster_id]
        
        # Urutkan titik berdasarkan koordinat x untuk konsistensi
        cluster_points = cluster_points.sort_values('x')
        
        # Bagi menjadi kelompok-kelompok dengan maksimal 16 HP
        for i in range(0, len(cluster_points), max_hp_per_fat):
            chunk = cluster_points.iloc[i:i+max_hp_per_fat]
            chunk['fat_name'] = f'FAT A{fat_id:02d}'
            fat_zones.append(chunk)
            fat_id += 1
    
    fat_areas = pd.concat(fat_zones)
    return fat_areas

def create_fat_polygons(fat_areas):
    """Buat polygon convex hull untuk setiap area FAT"""
    fat_polygons = []
    
    for fat_name in fat_areas['fat_name'].unique():
        group = fat_areas[fat_areas['fat_name'] == fat_name]
        
        # Buat multipoint dan convex hull
        multipoint = MultiPoint(group.geometry.tolist())
        convex_hull = multipoint.convex_hull
        
        # Tambahkan buffer 20 meter (konversi ke UTM untuk buffer akurat)
        utm_crs = CRS.from_epsg(32748)
        wgs84_crs = CRS.from_epsg(4326)
        transformer = Transformer.from_crs(wgs84_crs, utm_crs, always_xy=True)
        
        # Transformasi ke UTM, buffer, lalu kembalikan ke WGS84
        hull_utm = transform_geometry(convex_hull, transformer)
        buffered_hull = hull_utm.buffer(20)
        buffered_hull_wgs84 = transform_geometry(buffered_hull, transformer, reverse=True)
        
        fat_polygons.append({
            'name': fat_name,
            'hp_count': len(group),
            'geometry': buffered_hull_wgs84
        })
    
    return fat_polygons

def transform_geometry(geom, transformer, reverse=False):
    """Transformasi geometry antara CRS"""
    if geom.is_empty:
        return geom
    
    if geom.geom_type == 'Point':
        x, y = transformer.transform(geom.x, geom.y) if not reverse else transformer.transform(geom.x, geom.y, direction='INVERSE')
        return Point(x, y)
    elif geom.geom_type == 'Polygon':
        exterior = geom.exterior
        new_exterior = []
        for x, y in exterior.coords:
            tx, ty = transformer.transform(x, y) if not reverse else transformer.transform(x, y, direction='INVERSE')
            new_exterior.append((tx, ty))
        
        interiors = []
        for interior in geom.interiors:
            new_interior = []
            for x, y in interior.coords:
                tx, ty = transformer.transform(x, y) if not reverse else transformer.transform(x, y, direction='INVERSE')
                new_interior.append((tx, ty))
            interiors.append(new_interior)
        
        return Polygon(new_exterior, interiors)
    elif geom.geom_type == 'MultiPoint':
        points = []
        for point in geom.geoms:
            x, y = transformer.transform(point.x, point.y) if not reverse else transformer.transform(point.x, point.y, direction='INVERSE')
            points.append(Point(x, y))
        return MultiPoint(points)
    return geom

def export_to_kml(fat_polygons, output_kml):
    """Export FAT polygons ke file KML"""
    kml = simplekml.Kml()
    
    for fat in fat_polygons:
        # Buat polygon untuk FAT area
        if fat['geometry'].geom_type == 'Polygon':
            pol = kml.newpolygon(
                name=fat['name'],
                description=f"{fat['hp_count']} HP",
                outerboundaryis=[(x, y) for x, y in fat['geometry'].exterior.coords]
            )
            
            # Atur style
            pol.style.polystyle.color = simplekml.Color.changealphaint(50, simplekml.Color.green)
            pol.style.linestyle.color = simplekml.Color.red
            pol.style.linestyle.width = 2
            
            # Tambahkan label di centroid
            centroid = fat['geometry'].centroid
            kml.newpoint(
                name=fat['name'],
                coords=[(centroid.x, centroid.y)],
                styleurl='#label_style'
            )
    
    # Buat style untuk label
    label_style = kml.newstyle(id='label_style')
    label_style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png'
    label_style.labelstyle.scale = 0.8  # Ukuran label
    
    kml.save(output_kml)

def main():
    # Konfigurasi
    input_kml = "input_homepass.kml"  # Ganti dengan file input Anda
    output_kml = "fat_areas_output.kml"
    max_hp_per_fat = 16
    max_distance_m = 100  # meter
    
    print("Memulai proses pengelompokan FAT areas...")
    
    # 1. Muat dan persiapkan data
    print("Memuat data KML...")
    points_gdf = load_and_prepare_data(input_kml)
    print(f"Ditemukan {len(points_gdf)} titik/segmen HomePass")
    
    # 2. Kelompokkan titik
    print("Mengelompokkan titik...")
    clustered_points = cluster_points(points_gdf, max_distance_m)
    print(f"Dihasilkan {clustered_points['cluster'].nunique()} cluster awal")
    
    # 3. Buat area FAT
    print("Membuat area FAT...")
    fat_areas = create_fat_areas(clustered_points, max_hp_per_fat)
    print(f"Dihasilkan {fat_areas['fat_name'].nunique()} area FAT")
    
    # 4. Buat polygon FAT
    print("Membuat polygon FAT...")
    fat_polygons = create_fat_polygons(fat_areas)
    
    # 5. Export ke KML
    print("Mengekspor ke KML...")
    export_to_kml(fat_polygons, output_kml)
    print(f"✅ Selesai! Output disimpan sebagai {output_kml}")

if __name__ == "__main__":
    main()
