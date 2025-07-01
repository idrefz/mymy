import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPoint, Polygon
from sklearn.cluster import DBSCAN
import simplekml
import numpy as np

# ====== SETUP ======
input_kml = "Myrep-KML PLAN GRAHA CIBADAK.kml"  # Change filename as needed
output_kml = "output_fat_area.kml"
max_hp_per_fat = 16  # Maximum HPs per FAT area
max_distance_m = 100  # Maximum distance between points in a cluster (meters)
utm_epsg = 32748  # UTM zone for West Indonesia (WGS 84 / UTM zone 48S)
buffer_distance = 20  # Buffer distance around convex hull (meters)

# ====== LOAD AND PREPARE DATA ======
def load_and_prepare_data():
    """Load KML file and prepare GeoDataFrame"""
    try:
        gdf = gpd.read_file(input_kml, driver='KML')
        if gdf.empty:
            raise ValueError("Input KML file is empty")
        
        # Convert to UTM for accurate distance measurements
        gdf = gdf.to_crs(epsg=utm_epsg)
        
        # Extract coordinates for clustering
        gdf['x'] = gdf.geometry.x
        gdf['y'] = gdf.geometry.y
        
        return gdf
    except Exception as e:
        print(f"Error loading KML file: {str(e)}")
        raise

# ====== CLUSTERING ======
def perform_clustering(gdf):
    """Perform DBSCAN clustering on the points"""
    try:
        coords = gdf[['x', 'y']].values
        
        # DBSCAN clustering
        db = DBSCAN(eps=max_distance_m, min_samples=1).fit(coords)
        gdf['cluster'] = db.labels_
        
        # Validate clustering results
        if len(gdf['cluster'].unique()) == 0:
            raise ValueError("Clustering failed - no clusters identified")
            
        return gdf
    except Exception as e:
        print(f"Error during clustering: {str(e)}")
        raise

# ====== CREATE FAT AREAS ======
def create_fat_areas(gdf):
    """Create FAT areas by grouping clusters into chunks"""
    try:
        fat_zones = []
        fat_id = 1
        
        for cid in gdf['cluster'].unique():
            sub = gdf[gdf['cluster'] == cid].copy()
            
            # Sort points by x coordinate for consistent grouping
            sub = sub.sort_values('x')
            
            # Split into chunks of max_hp_per_fat
            for i in range(0, len(sub), max_hp_per_fat):
                chunk = sub.iloc[i:i+max_hp_per_fat].copy()
                chunk['fat'] = f'FAT_A{fat_id:02}'
                fat_zones.append(chunk)
                fat_id += 1
                
        if not fat_zones:
            raise ValueError("No FAT areas created")
            
        return pd.concat(fat_zones)
    except Exception as e:
        print(f"Error creating FAT areas: {str(e)}")
        raise

# ====== GENERATE FAT POLYGONS ======
def generate_fat_polygons(fat_gdf):
    """Generate convex hull polygons for each FAT area"""
    try:
        fat_polygons = []
        
        for fat_name in fat_gdf['fat'].unique():
            group = fat_gdf[fat_gdf['fat'] == fat_name]
            
            # Create MultiPoint from all points in FAT area
            multipoint = MultiPoint(group.geometry.tolist())
            
            # Generate convex hull and add buffer
            convex_hull = multipoint.convex_hull
            buffered_hull = convex_hull.buffer(buffer_distance)
            
            # Handle different geometry types
            if buffered_hull.geom_type == "Polygon":
                fat_polygons.append({
                    'name': fat_name,
                    'count': len(group),
                    'geometry': buffered_hull
                })
            elif buffered_hull.geom_type == "MultiPolygon":
                # Take the largest polygon if it's a multipolygon
                largest = max(buffered_hull.geoms, key=lambda p: p.area)
                fat_polygons.append({
                    'name': fat_name,
                    'count': len(group),
                    'geometry': largest
                })
                
        return fat_polygons
    except Exception as e:
        print(f"Error generating FAT polygons: {str(e)}")
        raise

# ====== EXPORT TO KML ======
def export_to_kml(fat_polygons):
    """Export FAT polygons to KML file"""
    try:
        kml = simplekml.Kml()
        
        for fat in fat_polygons:
            # Convert polygon coordinates back to lat/lon (WGS84)
            polygon_geom = fat['geometry']
            
            # Create a temporary GeoDataFrame to reproject
            temp_gdf = gpd.GeoDataFrame(geometry=[polygon_geom], crs=f"EPSG:{utm_epsg}")
            temp_gdf = temp_gdf.to_crs(epsg=4326)  # WGS84
            
            # Get coordinates in lat/lon
            polygon_wgs84 = temp_gdf.geometry.iloc[0]
            
            # Create KML polygon
            pol = kml.newpolygon(
                name=fat['name'],
                description=f"Contains {fat['count']} HPs",
                outerboundaryis=[(p[0], p[1]) for p in polygon_wgs84.exterior.coords]
            )
            pol.style.polystyle.color = simplekml.Color.changealphaint(100, simplekml.Color.green)
            pol.style.linestyle.color = simplekml.Color.red
            pol.style.linestyle.width = 2
            
        kml.save(output_kml)
        print(f"✅ Successfully saved to: {output_kml}")
        print(f"Total FAT areas created: {len(fat_polygons)}")
    except Exception as e:
        print(f"Error exporting to KML: {str(e)}")
        raise

# ====== MAIN EXECUTION ======
if __name__ == "__main__":
    try:
        print("Starting FAT area creation process...")
        
        # Step 1: Load and prepare data
        print("Loading KML file...")
        gdf = load_and_prepare_data()
        print(f"Loaded {len(gdf)} points")
        
        # Step 2: Perform clustering
        print("Performing clustering...")
        gdf = perform_clustering(gdf)
        print(f"Identified {len(gdf['cluster'].unique())} clusters")
        
        # Step 3: Create FAT areas
        print("Creating FAT areas...")
        fat_gdf = create_fat_areas(gdf)
        
        # Step 4: Generate FAT polygons
        print("Generating FAT polygons...")
        fat_polygons = generate_fat_polygons(fat_gdf)
        
        # Step 5: Export to KML
        print("Exporting to KML...")
        export_to_kml(fat_polygons)
        
        print("Process completed successfully!")
    except Exception as e:
        print(f"❌ Error in main execution: {str(e)}")