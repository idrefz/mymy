import simplekml
import geopandas as gpd
import pandas as pd
import shapely
from shapely.geometry import Point, box
import matplotlib.pyplot as plt

# -------------------------
# 1. Load titik Homepass dari file KML
# -------------------------
gdf = gpd.read_file("homepass.kml", driver='KML')  # file KML harus disiapkan dari Google Earth
gdf['geometry'] = gdf['geometry'].to_crs(epsg=32748)  # UTM zone 48S (Indonesia Barat)

# -------------------------
# 2. Konversi ke koordinat UTM agar bisa dihitung meter
# -------------------------
gdf_utm = gdf.to_crs(epsg=32748)  # Ganti UTM zone sesuai lokasi
points = gdf_utm['geometry'].copy()

# -------------------------
# 3. Buat Grid Persegi 250 m² (15.8 m x 15.8 m)
# -------------------------
minx, miny, maxx, maxy = gdf_utm.total_bounds
grid_size = 15.8
polygons = []
while minx < maxx:
    y = miny
    while y < maxy:
        polygons.append(box(minx, y, minx + grid_size, y + grid_size))
        y += grid_size
    minx += grid_size

grid = gpd.GeoDataFrame({'geometry': polygons}, crs='EPSG:32748')

# -------------------------
# 4. Spatial Join: Hitung jumlah titik dalam setiap grid
# -------------------------
join = gpd.sjoin(grid, gdf_utm, how="left", predicate="contains")
counts = join.groupby('index_left').size()
grid['homepass'] = counts.fillna(0)

# -------------------------
# 5. Tambah Warna: Merah jika > 16
# -------------------------
grid['color'] = grid['homepass'].apply(lambda x: 'ff00ff00' if x <= 16 else 'ff0000ff')  # KML color is ABGR

# -------------------------
# 6. Export ke KML
# -------------------------
kml = simplekml.Kml()
for _, row in grid.iterrows():
    pol = kml.newpolygon(name=f"{int(row['homepass'])} Homepass",
                         outerboundaryis=[(p[0], p[1]) for p in row['geometry'].exterior.coords])
    pol.style.polystyle.color = row['color']
    pol.style.linestyle.width = 1

kml.save("grid_output.kml")
