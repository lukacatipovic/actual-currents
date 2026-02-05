from flask import Flask, jsonify, request, send_from_directory
import numpy as np
import iris
import pytz
from datetime import datetime
from matplotlib.dates import date2num
from utide.utilities import loadbunch
from ttide.t_vuf import t_vuf
from scipy.interpolate import griddata
import warnings
import os
import traceback

app = Flask(__name__)

# Global API instance
tidal_api = None

def init_tidal_api():
    """Initialize the tidal API once"""
    global tidal_api
    if tidal_api is None:
        try:
            tidal_api = TidalCurrentsAPI('data/adcirc54.nc')
            print("✅ Tidal API initialized successfully")
        except Exception as e:
            print(f"❌ Failed to initialize Tidal API: {e}")
            print("⚠️  Using dummy data mode")
            tidal_api = None
    return tidal_api

class TidalCurrentsAPI:
    """Tidal currents calculator with dynamic bounding boxes"""
    def __init__(self, ncfile):
        print(f"📁 Loading data from {ncfile}...")
        self.ncfile = ncfile
        
        # Default bounding box (Woods Hole area)
        self.default_bbox = {'west': -70.72, 'east': -70.6, 
                            'south': 41.4, 'north': 41.55}
        
        self.constituents = ['M2', 'S2', 'N2', 'K1', 'O1', 'P1', 'M4', 'M6']
        
        # Load ALL data (not filtered by bbox yet)
        self._load_all_data()
        print(f"✅ Loaded {len(self.all_lon)} total stations")
    
    def _load_all_data(self):
        """Load all data from file without filtering"""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cubes = iris.load_raw(self.ncfile)
        
        # Get all locations
        self.all_lon = cubes.extract_cube('longitude').data.astype(float)
        self.all_lat = cubes.extract_cube('latitude').data.astype(float)
        
        print(f"📊 Full dataset bounds:")
        print(f"  Longitude: {self.all_lon.min():.6f} to {self.all_lon.max():.6f}")
        print(f"  Latitude: {self.all_lat.min():.6f} to {self.all_lat.max():.6f}")
        print(f"  Total points: {len(self.all_lon)}")
        
        # Get constituent indices
        all_names = cubes.extract_cube('Tide Constituent').data
        def parse(name): 
            return ''.join([e.decode().strip() for e in name.tolist() if e])
        const_names = [parse(name) for name in all_names]
        
        self.const_indices = []
        for const in self.constituents:
            try: 
                self.const_indices.append(const_names.index(const))
                print(f"  ✅ Found constituent: {const}")
            except: 
                print(f"  ⚠️  Constituent {const} not found")
        
        if not self.const_indices:
            raise ValueError("No valid constituents found!")
        
        print(f"  Using {len(self.const_indices)} constituents")
        
        # Load all amplitude and phase data
        self.all_u_amp = cubes.extract_cube('Eastward Water Velocity Amplitude').data[0, :, :][:, self.const_indices].astype(float)
        self.all_u_pha = cubes.extract_cube('Eastward Water Velocity Phase').data[0, :, :][:, self.const_indices].astype(float)
        self.all_v_amp = cubes.extract_cube('Northward Water Velocity Amplitude').data[0, :, :][:, self.const_indices].astype(float)
        self.all_v_pha = cubes.extract_cube('Northward Water Velocity Phase').data[0, :, :][:, self.const_indices].astype(float)
        
        # Load frequencies
        freq = cubes.extract_cube('Tide Frequency').data[self.const_indices] * 3600
        self.freq = freq.astype(float)
        
        # Load constants for ttide nodal corrections
        try:
            con_info = loadbunch('data/ut_constants.npz')['const']
            const_list = [e.strip() for e in con_info['name'].tolist()]
            self.const_indices_ttide = []
            for c in self.constituents:
                if c in const_list:
                    self.const_indices_ttide.append(const_list.index(c))
                else:
                    print(f"  ⚠️  Constituent {c} not in ttide constants, using index fallback")
                    self.const_indices_ttide.append(0)  # Fallback
            
            print(f"  ✅ Loaded ttide constants for {len(self.const_indices_ttide)} constituents")
        except Exception as e:
            print(f"⚠️  Failed to load ttide constants: {e}")
            print("   Using fallback indices")
            self.const_indices_ttide = list(range(len(self.const_indices)))
    
    def calculate_for_points(self, time_utc, lon, lat, u_amp, u_pha, v_amp, v_pha):
        """Calculate U/V for specific points and time"""
        jd = date2num(time_utc) + 366
        
        v_node, u_node, f_node = t_vuf('nodal', jd, ju=np.array(self.const_indices_ttide), lat=55)
        v_node, u_node, f_node = map(np.squeeze, (v_node, u_node, f_node))
        v_node, u_node = v_node * 2 * np.pi, u_node * 2 * np.pi
        
        # Calculate time difference from reference time (2000-01-01)
        ref_time = datetime(2000, 1, 1, tzinfo=pytz.UTC)
        hours = (time_utc - ref_time).total_seconds() / 3600
        omega_t = self.freq * hours
        
        U = np.zeros(len(lon))
        V = np.zeros(len(lon))
        
        for i in range(len(self.const_indices)):
            phase_u = v_node[i] + omega_t[i] + u_node[i] - u_pha[:, i] * np.pi/180
            phase_v = v_node[i] + omega_t[i] + u_node[i] - v_pha[:, i] * np.pi/180
            U += f_node[i] * u_amp[:, i] * np.cos(phase_u)
            V += f_node[i] * v_amp[:, i] * np.cos(phase_v)
        
        return U, V
    
    def get_grid(self, time_str, timezone='EST', res=0.01, bbox=None):
        """Get interpolated grid data for specific bounds"""
        if bbox is None:
            bbox = self.default_bbox
        
        print(f"🎯 Generating grid:")
        print(f"  Bbox: west={bbox['west']:.6f}, east={bbox['east']:.6f}")
        print(f"        south={bbox['south']:.6f}, north={bbox['north']:.6f}")
        print(f"  Resolution: {res}")
        
        # Parse time with robust EST/EDT handling
        time_utc = self.parse_time_string(time_str, timezone)
        print(f"  Time: {time_str} {timezone} → {time_utc} UTC")
        
        # Filter data to requested bbox
        inbox = np.logical_and(
            np.logical_and(self.all_lon >= bbox['west'], self.all_lon <= bbox['east']),
            np.logical_and(self.all_lat >= bbox['south'], self.all_lat <= bbox['north'])
        )
        
        print(f"📈 Points in bbox: {np.sum(inbox)} (out of {len(self.all_lon)})")
        
        if np.sum(inbox) == 0:
            print("⚠️  No points in bbox, using dummy data")
            return self._get_dummy_grid(bbox, res)
        
        # Extract filtered data
        lon = self.all_lon[inbox]
        lat = self.all_lat[inbox]
        u_amp = self.all_u_amp[inbox, :]
        u_pha = self.all_u_pha[inbox, :]
        v_amp = self.all_v_amp[inbox, :]
        v_pha = self.all_v_pha[inbox, :]
        
        # Remove any remaining NaN values
        mask = ~(np.isnan(lon) | np.isnan(lat) | 
                 np.any(np.isnan(u_amp), axis=1) | np.any(np.isnan(v_amp), axis=1))
        
        if np.sum(mask) == 0:
            print("❌ All points have NaN values after filtering")
            return self._get_dummy_grid(bbox, res)
        
        lon = lon[mask]
        lat = lat[mask]
        u_amp = u_amp[mask, :]
        u_pha = u_pha[mask, :]
        v_amp = v_amp[mask, :]
        v_pha = v_pha[mask, :]
        
        print(f"📊 Valid points after NaN removal: {len(lon)}")
        
        # Calculate currents for filtered points
        U, V = self.calculate_for_points(time_utc, lon, lat, u_amp, u_pha, v_amp, v_pha)
        
        # Create grid
        lon_min, lon_max = bbox['west'], bbox['east']
        lat_min, lat_max = bbox['south'], bbox['north']
        
        # Calculate number of grid cells
        nx = max(2, int((lon_max - lon_min) / res) + 1)
        ny = max(2, int((lat_max - lat_min) / res) + 1)
        
        print(f"📐 Grid dimensions: {ny} rows × {nx} cols = {ny * nx:,} cells")
        
        # Limit maximum cells for performance
        MAX_CELLS = 30000
        if ny * nx > MAX_CELLS:
            print(f"⚠️  Grid too large ({ny*nx:,} cells), adjusting resolution")
            # Find resolution that gives ~MAX_CELLS
            area = (lon_max - lon_min) * (lat_max - lat_min)
            optimal_res = np.sqrt(area / MAX_CELLS)
            nx = max(2, int((lon_max - lon_min) / optimal_res) + 1)
            ny = max(2, int((lat_max - lat_min) / optimal_res) + 1)
            print(f"   New resolution: {optimal_res:.6f}, grid: {ny}×{nx} = {ny*nx:,} cells")
            res = optimal_res
        
        grid_lon, grid_lat = np.meshgrid(
            np.linspace(lon_min, lon_max, nx),
            np.linspace(lat_min, lat_max, ny)
        )
        
        # Interpolate to grid
        U_grid = griddata((lon, lat), U, (grid_lon, grid_lat), method='linear', fill_value=0.0)
        V_grid = griddata((lon, lat), V, (grid_lon, grid_lat), method='linear', fill_value=0.0)
        
        # Apply land mask if shapefile exists
        try:
            import geopandas as gpd
            from rasterio import features
            from affine import Affine
            
            # Load shapefile
            shapefile_path = 'data/New_England_States.shp'
            if os.path.exists(shapefile_path):
                gdf = gpd.read_file(shapefile_path)
                if gdf.crs != 'EPSG:4326':
                    gdf = gdf.to_crs('EPSG:4326')
                
                # Create transform
                dx = grid_lon[0, 1] - grid_lon[0, 0]
                dy = grid_lat[1, 0] - grid_lat[0, 0]
                transform = Affine.translation(grid_lon[0, 0] - dx/2, grid_lat[0, 0] - dy/2) * Affine.scale(dx, dy)
                
                # Create land mask
                shapes = [(geom, 1) for geom in gdf.geometry]
                land_mask = features.rasterize(shapes, out_shape=(ny, nx), 
                                              transform=transform, fill=0, dtype=np.uint8)
                
                # Mask out land cells
                ocean_mask = (land_mask == 0)
                U_grid[~ocean_mask] = 0.0
                V_grid[~ocean_mask] = 0.0
                
                print(f"✅ Applied land mask: {np.sum(~ocean_mask)} land cells")
            else:
                print(f"📝 Shapefile not found at {shapefile_path}, skipping land mask")
                
        except Exception as e:
            print(f"📝 Note: Land masking skipped ({e})")
        
        return {
            'U': U_grid.tolist(),
            'V': V_grid.tolist(),
            'lons': grid_lon[0, :].tolist(),
            'lats': grid_lat[:, 0].tolist(),
            'shape': [ny, nx],
            'bbox_used': bbox,
            'resolution_used': res
        }
    
    def parse_time_string(self, time_str, timezone):
        """Parse time string with robust timezone handling"""
        try:
            # Try multiple date formats
            formats = [
                '%Y-%m-%d %H:%M',      # 2024-01-15 14:30
                '%d-%b-%Y %H:%M',      # 15-Jan-2024 14:30
                '%Y/%m/%d %H:%M',      # 2024/01/15 14:30
                '%m/%d/%Y %H:%M',      # 01/15/2024 14:30
                '%Y-%m-%dT%H:%M',      # 2024-01-15T14:30 (ISO-like)
            ]
            
            naive = None
            for fmt in formats:
                try:
                    naive = datetime.strptime(time_str, fmt)
                    break
                except ValueError:
                    continue
            
            if naive is None:
                # If no format works, try to parse with dateutil (if available)
                try:
                    from dateutil import parser
                    naive = parser.parse(time_str)
                    print(f"📅 Used dateutil to parse: {time_str}")
                except:
                    naive = datetime.now()
                    print(f"⚠️  Invalid time format: {time_str}, using current time")
            
            # Convert to appropriate timezone
            if timezone.upper() in ['EST', 'EDT', 'ET']:
                # US/Eastern automatically handles EST/EDT based on date
                eastern = pytz.timezone('US/Eastern')
                time_local = eastern.localize(naive)
                time_utc = time_local.astimezone(pytz.UTC)
            elif timezone.upper() == 'UTC':
                time_utc = naive.replace(tzinfo=pytz.UTC)
            else:
                # Try to use the timezone directly
                try:
                    tz = pytz.timezone(timezone)
                    time_local = tz.localize(naive)
                    time_utc = time_local.astimezone(pytz.UTC)
                except:
                    print(f"⚠️  Unknown timezone: {timezone}, assuming UTC")
                    time_utc = naive.replace(tzinfo=pytz.UTC)
            
            return time_utc
            
        except Exception as e:
            print(f"⚠️  Error parsing time: {e}, using current UTC time")
            return datetime.now(pytz.UTC)
    
    def _get_dummy_grid(self, bbox, res):
        """Return a simple dummy grid when no data is available"""
        print("⚠️  Returning dummy grid pattern")
        
        # Create a simple grid with a circular current pattern
        lon_min, lon_max = bbox['west'], bbox['east']
        lat_min, lat_max = bbox['south'], bbox['north']
        
        nx = max(2, int((lon_max - lon_min) / res) + 1)
        ny = max(2, int((lat_max - lat_min) / res) + 1)
        
        grid_lon, grid_lat = np.meshgrid(
            np.linspace(lon_min, lon_max, nx),
            np.linspace(lat_min, lat_max, ny)
        )
        
        # Create a simple circular current pattern
        center_lon = (lon_min + lon_max) / 2
        center_lat = (lat_min + lat_max) / 2
        
        U_grid = np.zeros((ny, nx))
        V_grid = np.zeros((ny, nx))
        
        for i in range(ny):
            for j in range(nx):
                dx = grid_lon[i, j] - center_lon
                dy = grid_lat[i, j] - center_lat
                distance = np.sqrt(dx*dx + dy*dy) + 0.0001
                # Circular pattern
                U_grid[i, j] = -dy / distance * 0.3
                V_grid[i, j] = dx / distance * 0.3
        
        return {
            'U': U_grid.tolist(),
            'V': V_grid.tolist(),
            'lons': grid_lon[0, :].tolist(),
            'lats': grid_lat[:, 0].tolist(),
            'shape': [ny, nx],
            'bbox_used': bbox,
            'resolution_used': res,
            'dummy_data': True
        }

@app.route('/')
def index():
    """Serve the main page"""
    return send_from_directory('.', 'index.html')

@app.route('/app.js')
def serve_js():
    """Serve the JavaScript file"""
    return send_from_directory('.', 'app.js')

@app.route('/currents')
def get_currents():
    """API endpoint for tidal currents with dynamic bounding box"""
    try:
        # Initialize API
        api = init_tidal_api()
        
        if api is None:
            print("⚠️  API not initialized, returning dummy data")
            return jsonify({
                'success': True,
                'U': [[0.1, 0.2], [0.3, 0.4]],
                'V': [[0.05, 0.1], [0.15, 0.2]],
                'lons': [-70.7, -70.6],
                'lats': [41.5, 41.6],
                'shape': [2, 2],
                'dummy_data': True
            })
        
        # Get parameters
        time_str = request.args.get('time', datetime.now().strftime('%Y-%m-%d %H:%M'))
        timezone = request.args.get('timezone', 'EST')
        resolution = float(request.args.get('resolution', 0.01))
        
        # Get view bounds if provided
        north = request.args.get('north', type=float)
        south = request.args.get('south', type=float)
        east = request.args.get('east', type=float)
        west = request.args.get('west', type=float)
        
        # Create bbox from parameters or use default
        if all([north, south, east, west]):
            bbox = {
                'north': north,
                'south': south,
                'east': east,
                'west': west
            }
            print(f"🎯 Using provided bbox: {bbox}")
        else:
            bbox = api.default_bbox
            print(f"📌 Using default bbox: {bbox}")
        
        print(f"🌊 Request: time={time_str}, tz={timezone}, res={resolution}")
        
        # Get data
        data = api.get_grid(time_str, timezone, resolution, bbox)
        
        return jsonify({
            'success': True,
            'U': data['U'],
            'V': data['V'],
            'lons': data['lons'],
            'lats': data['lats'],
            'shape': data['shape'],
            'time': time_str,
            'timezone': timezone,
            'resolution': data.get('resolution_used', resolution),
            'bbox': data.get('bbox_used', bbox),
            'dummy_data': data.get('dummy_data', False)
        })
        
    except Exception as e:
        print(f"❌ Error in /currents endpoint: {e}")
        print(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': str(e),
            'U': [[0.1, 0.2], [0.3, 0.4]],
            'V': [[0.05, 0.1], [0.15, 0.2]],
            'lons': [-70.7, -70.6],
            'lats': [41.5, 41.6],
            'shape': [2, 2],
            'dummy_data': True
        })

@app.route('/dataset_info')
def dataset_info():
    """Return information about the dataset coverage"""
    try:
        api = init_tidal_api()
        if api is None:
            return jsonify({'error': 'API not initialized'})
        
        return jsonify({
            'success': True,
            'full_bounds': {
                'lon_min': float(api.all_lon.min()),
                'lon_max': float(api.all_lon.max()),
                'lat_min': float(api.all_lat.min()),
                'lat_max': float(api.all_lat.max())
            },
            'total_points': len(api.all_lon),
            'constituents': api.constituents,
            'default_bbox': api.default_bbox
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'service': 'tidal-currents',
        'timestamp': datetime.now().isoformat(),
        'api_initialized': tidal_api is not None
    })

if __name__ == '__main__':
    print("=" * 60)
    print("🌊 TIDAL CURRENTS SERVER v2.0")
    print("=" * 60)
    print("Features:")
    print("  • Dynamic bounding box support")
    print("  • Adaptive resolution")
    print("  • Zoom-aware data loading")
    print("  • Proper EST/EDT timezone handling")
    print("=" * 60)
    print("Serving at: http://localhost:5555")
    print("Endpoints:")
    print("  /             - Map visualization")
    print("  /currents     - Get tidal currents (supports bbox params)")
    print("  /dataset_info - Get dataset bounds and info")
    print("  /health       - Health check")
    print("\n📁 Expected data files:")
    print("  data/adcirc54.nc")
    print("  data/ut_constants.npz")
    print("  data/New_England_States.shp (optional, for land masking)")
    print("=" * 60)
    
    # Enable CORS
    @app.after_request
    def after_request(response):
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET')
        return response
    
    # Try to initialize API
    init_tidal_api()
    
    # Start server
    app.run(host='0.0.0.0', port=5555, debug=True)