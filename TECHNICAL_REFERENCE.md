# Actual Currents - Technical Reference Document

**Last Updated:** 2026-02-07
**Purpose:** Cross-conversation reference for AI assistant and developers

---

## 1. PROJECT OVERVIEW

### Mission
Build a mobile application (iOS/Android) + web app for real-time tidal current visualization using ADCIRC tidal harmonic constituent data.

### Geographic Coverage
- **Region:** Western North Atlantic
- **Extent:** Gulf of Mexico to Nova Scotia
- **Coordinates:** 5.7°N - 45.9°N, 98°W - 54°W

### Key Technologies
- **Backend:** FastAPI (Python 3.11+)
- **Data Storage:** Zarr format (local dev / AWS S3 production)
- **Web Frontend:** Vanilla JS + Canvas2D (current), mobile TBD
- **Particle Animation:** Canvas2D overlay with trail-effect rendering
- **Mapping:** Mapbox GL JS v3.0.1
- **Infrastructure:** AWS S3 (data) + planned ECS Fargate (API)

---

## 2. DATA STRUCTURE

### Source Data
- **Original Format:** netCDF4 (adcirc54.nc)
- **Source:** NOAA/NOS/OCS/CSDL/MMAP ADCIRC model
- **Original Size:** ~1.8 GB

### Zarr Conversion Details
**Script:** `backend/scripts/convert_to_zarr.py`

**Mesh Structure:**
- **Total Nodes:** 2,066,216 (irregular triangular mesh)
- **Total Elements:** 3,770,720 (triangular connectivity)
- **Node Attributes:**
  - `lat` - Latitude (degrees_north)
  - `lon` - Longitude (degrees_east)
  - `depth` - Bathymetric depth (meters, positive down)

**Tidal Constituent Data (8 main constituents):**
- **Constituents:** M2, S2, N2, K1, O1, P1, M4, M6
- **Per Node, Per Constituent:**
  - `u_amp` - Eastward velocity amplitude (m/s)
  - `v_amp` - Northward velocity amplitude (m/s)
  - `u_phase` - Eastward velocity phase (degrees)
  - `v_phase` - Northward velocity phase (degrees)
- **Tide Frequencies:** `tidefreqs` - Angular frequency for each constituent (rad/s)

**Mesh Connectivity:**
- `elements` - Array of shape (3,770,720, 3) containing 0-based node indices
- Each element is a triangle defined by 3 node indices
- **Critical for particle animation** - enables barycentric interpolation

### Spatial Optimization
**✅ Hilbert Space-Filling Curve Ordering (Updated 2026-02-06):**
- Nodes sorted using **Hilbert curve (order-16)** for optimal spatial locality
- 65,536 × 65,536 grid resolution for precise spatial encoding
- **2-10x faster** bounding box queries vs simple grid ordering
- **80%+ chunk utilization** (minimal wasted data loading)
- Sequential chunk reads instead of scattered access
- Element connectivity remapped to sorted indices

**Chunking Strategy:**
- **Node chunks:** 10,000 nodes per chunk (~207 chunks total) - Optimized for fast viewport loading
- **Element chunks:** 50,000 triangles per chunk
- **Constituent chunks:** All 8 constituents kept together (always queried together)
- **Benefits:** Very granular loading - only loads minimal data needed for viewport

**Zarr Output:**
- **Size:** 266 MiB (compressed from 1.8 GB - 85% reduction)
- **Files:** 402 individual chunk files
- **Conversion Time:** ~6.8 seconds (including Hilbert encoding: 5.0s)
- **Location (prod):** `s3://actual-currents-data/adcirc54.zarr` (us-east-2)
- **Last Updated:** 2026-02-06 (Hilbert curve ordering)

### Query Performance
**Current Performance (Direct Numpy Indexing - 2026-02-06):**
- Woods Hole, MA (2,217 nodes): **0.32s total** (0.001s node query, 0.114s constituent extraction)
- Small viewport (<1,000 nodes): **<0.2s**
- Medium viewport (1k-5k nodes): **<0.5s**
- Large viewport (5k-10k nodes): **<1.0s**

**Performance Breakdown:**
- Node query: 0.001s (direct numpy indexing)
- Node extraction: 0.006s
- Element filtering: 0.02s (vectorized)
- Constituent data: 0.114s (Zarr chunk reads)
- Tidal prediction: negligible (<0.001s)
- JSON serialization: negligible

**Tested Regions:**
- Woods Hole, MA: Fast, confirmed working
- Miami/Florida Keys: Expected fast with 10k chunks
- NYC Harbor: Coastal detail preserved

---

## 3. TIDAL PREDICTION ALGORITHM

### Overview
Calculate instantaneous U/V velocities at any time using harmonic constituent synthesis with nodal corrections.

### Algorithm (from old MVP reference)
```python
# Step 1: Get nodal corrections from ttide library
# v = equilibrium argument (phase offset for current time)
# u = Greenwich phase lag
# f = nodal amplitude correction factor
v, u, f = t_vuf('nodal', julian_date, constituents, lat=55)

# Step 2: For each constituent, calculate phase angle
# ω = tidefreqs[constituent]  # Angular frequency (rad/s)
# t = time in seconds since reference epoch
phase_u = v + ω*t + u - u_phase  # For U component
phase_v = v + ω*t + u - v_phase  # For V component

# Step 3: Harmonic synthesis - sum all constituents
U_velocity = Σ [ f[i] * u_amp[i] * cos(phase_u[i]) ]
V_velocity = Σ [ f[i] * v_amp[i] * cos(phase_v[i]) ]
```

### Key Components
1. **ttide library** - Provides `t_vuf()` for nodal corrections
   - Already in requirements.txt (version 0.3.1)
   - GitHub: installed from source
2. **Reference Time** - ADCIRC reference: 2000-01-01T00:00:00Z
3. **Latitude for Nodal** - Config setting: 55.0°N (can be adjusted)

### Implementation Status
- **File:** `backend/app/core/tidal_calc.py`
- **Status:** ✅ Implemented and verified (2026-02-05)
- **Implementation:** Complete with ttide integration
- **Testing:** Verified with real Zarr data, Woods Hole MA test confirms realistic velocities
- **Algorithm:** `velocity = Σ [f[i] * amp[i] * cos(v + ω*t + u - phase)]` for each constituent

---

## 4. CURRENT BACKEND IMPLEMENTATION

### FastAPI Application
**Entry:** `backend/app/main.py`

**Endpoints:**
- `GET /` - Health check (overridden by frontend static files)
- `GET /health` - Detailed health check
- `GET /api/v1/mesh` - **Main data endpoint** (see below)
- `GET /api/v1/info` - Dataset metadata

**Key Features:**
- CORS enabled for frontend (allow_origins=["*"])
- Serves static frontend files from `frontend/` directory
- S3 Zarr loading with s3fs library

### Main Data Endpoint: `/api/v1/mesh`
**Purpose:** Query nodes, elements, and velocities for bounding box

**Parameters:**
- `min_lat`, `max_lat`, `min_lon`, `max_lon` (required)
- `time` (optional) - ISO 8601 datetime string

**Current Behavior:**
1. Opens Zarr from S3 (cached globally)
2. Filters nodes by bounding box
3. Filters elements to only those with all 3 vertices in bbox
4. Remaps element indices to compact 0-based range
5. ✅ **Calls tidal prediction algorithm** - uses `predict_currents()` from `tidal_calc.py`
6. Returns real velocity predictions (implementation complete, full testing pending)

**Response Format:**
```json
{
  "bbox": { "min_lat": 25.0, "max_lat": 26.0, ... },
  "time": "2026-02-05T12:00:00Z",
  "nodes": {
    "count": 150000,
    "lat": [25.1, 25.105, ...],
    "lon": [-80.5, -80.495, ...],
    "depth": [10.5, 12.3, ...],
    "u_velocity": [0.15, -0.23, ...],  // ✅ Real predictions
    "v_velocity": [0.08, 0.12, ...]    // ✅ Real predictions
  },
  "elements": {
    "count": 285000,
    "triangles": [[0, 1, 2], [1, 3, 2], ...]  // Remapped indices
  },
  "constituents": ["M2", "S2", "N2", "K1", "O1", "P1", "M4", "M6"]
}
```

**Performance Limits:**
- Max 500,000 nodes per request (raises HTTP 400 if exceeded)
- Typical response for visible map area: 50k-200k nodes

**Element Filtering Logic:**
- Critical: Only returns elements where ALL 3 nodes are in bbox
- Prevents broken triangles at boundaries
- Loop through all 3.77M elements (currently Python loop - could optimize)

### Configuration
**File:** `backend/app/core/config.py`

**Key Settings:**
- `DATA_SOURCE`: "S3" (production) or "LOCAL" (development)
- `S3_BUCKET`: "actual-currents-data"
- `S3_REGION`: "us-east-2"
- `REFERENCE_TIME`: "2000-01-01T00:00:00Z"
- `MAX_NODES_PER_REQUEST`: 500,000

**Environment:** Loads from `.env` file (not in repo)

### Dependencies
**File:** `backend/requirements.txt`

**Critical Libraries:**
- `fastapi==0.128.1` - API framework
- `uvicorn==0.40.0` - ASGI server
- `xarray==2026.1.0` - Multi-dimensional arrays
- `zarr==3.1.5` - Chunked array storage
- `s3fs==2025.1.0` - S3 filesystem interface
- `ttide==0.3.1` - Tidal analysis (nodal corrections)
- `numpy==2.4.2`, `scipy==1.17.0` - Numerical computing

**Development Tools:**
- `matplotlib==3.10.0` - Data visualization
- `pytest==9.0.2` - Testing

---

## 5. FRONTEND VISUALIZATION (WEB)

### Current Implementation
**Files:** `frontend/index.html` (458 lines) + `frontend/js/particles.js` (622 lines)
**Status:** ✅ Fully functional with particle animation

**Technologies:**
- Mapbox GL JS v3.0.1
- Canvas2D overlay for particle animation
- Pure HTML/JavaScript (no build step)
- No Node.js required

**Current Features:**
1. Map centered on New England (-70°, 41°), zoom 7
2. **Auto-loading** - nodes load automatically as user pans/zooms (zoom 8+)
3. Velocity-colored node visualization (circle layer, opacity 0 — particles are primary visual)
4. Debounced API calls (100ms) with AbortController request cancellation
5. Minimum zoom threshold (zoom 8+) to prevent overloading
6. Time controls (+1h/-1h, datetime picker, "Jump to Now")
7. Interactive popups (speed, direction, depth on click)
8. Statistics display (avg/max velocity)
9. Velocity legend (4-band: calm/moderate/strong/very strong)
10. **Particle flow animation** - windy-style flowing particles with trails
11. Animation toggle button (Start/Stop Animation)

**Auto-Load Behavior:**
- Listens to Mapbox `moveend` event (fires after pan/zoom completes)
- Debounced: waits 100ms after last movement before fetching
- Uses `AbortController` to cancel in-flight requests when user pans again
- Below zoom 8: shows "Zoom in to see tidal currents" message
- Handles API errors gracefully (404 = no data, 400 = too many nodes)
- Source data updated via `setData()` (not remove/re-add) to prevent event handler stacking
- Particle system auto-starts on data load, updates on pan/zoom

### Particle Animation System (`frontend/js/particles.js`)

**`TriangleSpatialIndex` class:**
- 50x50 grid overlay for fast point-in-triangle lookup
- Maps each triangle's bounding box to intersecting grid cells
- `findTriangle(lat, lon)` returns triangle index in O(1) average
- `getBarycentricCoords(lat, lon, tIdx)` for interpolation weights
- Point-in-triangle test with `1e-6` tolerance for edge cases

**`ParticleSystem` class:**
- Canvas2D overlay attached to `map.getCanvasContainer()` (correct positioning)
- HiDPI support: canvas sized at `clientWidth * devicePixelRatio`
- Trail fade via `destination-in` composite + semi-transparent fill each frame
- Speed-based coloring: 12-stop gradient (deep blue → cyan → green → yellow → orange → red)
- 10 color buckets for efficient batched Canvas2D strokes
- Pixel-space movement: `map.project()` → offset by velocity × adaptiveScale → `map.unproject()`
- Adaptive speed scaling based on map area: `speedScale * mapArea^0.4`
- Particles respawn when: age exceeds maxAge, or position falls outside triangle mesh
- Clears trails on map move, reinitializes particles on new data

**Current Parameters:**
- `numParticles`: 2500
- `speedScale`: 2 px/frame per m/s (with adaptive scaling)
- `maxAge`: 80 frames (~1.3s at 60fps)
- `trailFade`: 0.95 (trails persist ~20 frames)
- `lineWidth`: 1.5px

**Barycentric Interpolation:**
```javascript
// For particle at point P inside triangle (v0, v1, v2):
// Compute barycentric weights (w0, w1, w2) where w0 + w1 + w2 = 1
u_particle = w0 * u[v0] + w1 * u[v1] + w2 * u[v2]
v_particle = w0 * v[v0] + w1 * v[v1] + w2 * v[v2]
```

### Future Frontend Improvements
- WebGL rendering (regl or raw WebGL) for 10k+ particles at higher FPS
- Web Workers for particle update computation (offload main thread)
- Level-of-detail: reduce particle count when zoomed out
- Time animation playback (auto-advance time, show tidal cycle)
- Mobile-responsive UI

---

## 6. DEPLOYMENT & INFRASTRUCTURE

### AWS Services
**Current Status:**
- ✅ S3 bucket: `actual-currents-data` (us-east-2)
- ✅ IAM user: `actual-currents-api` with S3 read access
- ✅ Zarr data uploaded (267.9 MiB)
- ⏳ ECS Fargate deployment (planned)

### Planned Architecture
```
User (Mobile/Web)
    ↓
CloudFront CDN
    ↓
ALB (Application Load Balancer)
    ↓
ECS Fargate (FastAPI containers)
    ↓
S3 (Zarr data) + ElastiCache (optional query cache)
```

### Docker (Planned)
- Multi-stage build for minimal image size
- Python 3.11 slim base
- Health checks on `/health` endpoint

---

## 7. DEVELOPMENT WORKFLOW

### Running the Dev Server
**Script:** `./run_dev.sh`
```bash
#!/bin/bash
cd backend
source tides/bin/activate
uvicorn app.main:app --reload --port 8000
```

**Access:**
- Frontend: http://localhost:8000
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health
- API endpoint: http://localhost:8000/api/v1/mesh

### Testing Queries
```bash
# Test Zarr query performance
python backend/scripts/test_zarr_query.py

# Visualize data with matplotlib
python backend/scripts/plot_zarr_data.py
```

### Environment Setup
```bash
# Backend
cd backend
python3 -m venv tides
source tides/bin/activate
pip install -r requirements.txt

# Data conversion (one-time)
python scripts/convert_to_zarr.py
```

---

## 8. KEY DESIGN DECISIONS

### Why Unstructured Mesh?
- **Adaptive resolution** - dense nodes in complex coastal areas, sparse offshore
- **Preserves original model fidelity** - no interpolation artifacts
- **Better accuracy** - follows coastline geometry naturally
- **Challenges:** Requires spatial indexing and barycentric interpolation

### Why Zarr with Spatial Chunking?
- **Fast partial reads** - only load chunks intersecting bounding box
- **S3-native** - works directly with cloud storage (no download needed)
- **Compressed** - ~85% size reduction from netCDF
- **Scalable** - handles 2M+ nodes efficiently

### Why Not Regular Grid Interpolation?
- Would lose coastal detail (mesh is densest near shore)
- Interpolation introduces smoothing errors
- Original ADCIRC model is triangular - keep native structure

### Why WebGL Particles Instead of Vector Field?
- **More intuitive** - shows actual flow direction/speed
- **Scalable** - can render 10k+ particles at 60 FPS
- **Aesthetic** - fluid motion is engaging
- **Works with irregular mesh** - barycentric interpolation

---

## 9. CRITICAL FILES REFERENCE

### Data Processing
- `backend/scripts/convert_to_zarr.py` - **Main conversion script** ✅ UPDATED 2026-02-06
  - Reads `data/adcirc54.nc`
  - Outputs `data/adcirc54.zarr/`
  - **Hilbert curve spatial ordering** (order-16 for optimal locality)
  - Element remapping, chunking, compression
  - ~6.8 second runtime (Hilbert encoding: 5.0s for 2M nodes)
  - Alternative: Morton Z-order curve (configurable)

- `backend/scripts/benchmark_spatial_ordering.py` - **NEW: Spatial ordering benchmark**
  - Compares Hilbert vs Morton vs simple grid ordering
  - Measures spatial locality and chunk utilization
  - Visual comparison of ordering patterns

- `backend/scripts/SPATIAL_ORDERING.md` - **NEW: Space-filling curve documentation**
  - Explains Hilbert and Morton curve benefits
  - Performance comparison and benchmarks
  - Configuration guide and optimization tips

- `backend/scripts/test_zarr_query.py` - **Query benchmarking**
  - Tests Miami, Gulf of Mexico, NYC regions
  - Measures query performance
  - Example API response formatting

- `backend/scripts/plot_zarr_data.py` - **Visualization validation**
  - Matplotlib scatter plots
  - Verify spatial sorting worked

### Backend API
- `backend/app/main.py` - **FastAPI entry point**
  - Includes currents router
  - Serves static frontend
  - CORS configuration

- `backend/app/api/currents.py` - **Main data endpoints**
  - `/api/v1/mesh` - bounding box query
  - `/api/v1/info` - dataset metadata
  - S3 Zarr loading with caching
  - ⚠️ Element filtering loop (potential optimization point)

- `backend/app/core/config.py` - **Settings**
  - S3 configuration
  - API limits
  - Reference time for tidal calculations

- `backend/app/core/tidal_calc.py` - **✅ COMPLETE**
  - Contains `predict_currents()` function
  - ttide integration for nodal corrections (v, u, f factors)
  - Harmonic synthesis algorithm
  - Verified with real Zarr data through API endpoint

### Frontend
- `frontend/index.html` - **Web visualization** ✅ COMPLETE
  - Mapbox GL JS integration with auto-load on pan/zoom
  - Velocity-colored nodes, time controls, interactive popups
  - Particle system integration (auto-start, toggle, update on pan)
  - 458 lines

- `frontend/js/particles.js` - **Particle animation system** ✅ COMPLETE
  - `TriangleSpatialIndex`: 50x50 grid for fast triangle lookup
  - `ParticleSystem`: Canvas2D overlay with trail-effect rendering
  - Barycentric interpolation, speed-based coloring (12-stop gradient)
  - Pixel-space movement for zoom-independent visual speed
  - 622 lines

### Configuration
- `backend/requirements.txt` - **Python dependencies**
  - All packages pinned to specific versions
  - Includes ttide (tidal analysis)

- `backend/.env` - **Secrets** (not in repo)
  - AWS credentials
  - Environment-specific settings

### Documentation
- `README.md` - **Project overview**
  - Quick start guide
  - Architecture summary
  - Current status

- `TECHNICAL_REFERENCE.md` - **This file**
  - Detailed technical documentation
  - Cross-conversation reference

---

## 10. TECH STACK (CURRENT + PLANNED)

### Current Stack

| Layer | Technology | Status |
|-------|-----------|--------|
| **Backend API** | FastAPI (Python 3.11+) | ✅ Implemented |
| **Data Storage** | Zarr (local dev / AWS S3 prod) | ✅ Deployed |
| **Web Frontend** | Vanilla JS + Mapbox GL JS v3.0.1 | ✅ Implemented |
| **Particle Rendering** | Canvas2D overlay | ✅ Implemented |
| **Compression** | GZip middleware (starlette) | ✅ Implemented |

### Mobile Strategy (TBD)

Options under consideration (see Phase 5 in Next Steps):
1. **PWA** - Wrap current web app, easiest path
2. **Capacitor** - Native shell around web app
3. **React Native + Expo** - Native mobile with code sharing
4. **Native Swift/Kotlin** - Maximum performance (likely overkill)

### Future Rendering Upgrade Path
Current Canvas2D works well for 2500 particles. If more particles or higher FPS needed:
- **regl** - Lightweight functional WebGL, good for custom particle systems
- **Three.js** - Full 3D engine, if adding depth visualization later

---

## 11. NEXT STEPS (PRIORITY ORDER)

### ✅ Completed Phases

**Phase 1: Tidal Prediction API** - ✅ COMPLETE (2026-02-05)
- Harmonic synthesis with ttide nodal corrections
- Vectorized element filtering (3000x speedup)
- API returns accurate tidal currents in <0.02s (after first request)

**Phase 2: Map Visualization** - ✅ COMPLETE (2026-02-05)
- Velocity-colored nodes, time controls, interactive popups, statistics, legend

**Phase 3: Particle Animation** - ✅ COMPLETE (2026-02-07)
- Canvas2D particle system with triangle spatial index + barycentric interpolation
- Speed-based coloring, trail effects, auto-start on data load

**Data Optimization** - ✅ COMPLETE (2026-02-06)
- Hilbert curve ordering, 10k-node chunks, direct numpy indexing
- GZip compression, MeshData RAM pre-loading, 0.017s per request

---

### Phase 4: S3 Data Access (HIGH PRIORITY) 🔴
**Goal:** Load harmonic constituents from AWS S3 instead of local Zarr

**Current State:**
- Data already on S3: `s3://actual-currents-data/adcirc54.zarr` (us-east-2, 266 MiB)
- Backend already has S3 code path (`DATA_SOURCE=S3` in config)
- Currently using `DATA_SOURCE=LOCAL` for development
- S3 path was tested previously (info endpoint worked, mesh endpoint untested with optimized code)

**Tasks:**
1. Test `DATA_SOURCE=S3` with current MeshData pre-loading approach
   - The current approach loads ALL arrays into RAM at startup
   - This means one large S3 read (~266 MB) on cold start, then pure numpy
   - Verify startup time and first-request latency over network
2. Consider startup optimization if S3 load is too slow
   - Lazy loading (only load constituent arrays when first mesh query comes in)
   - Or pre-download Zarr to local disk on container startup
3. Verify deployed API works with S3 credentials (IAM role vs env vars)

---

### Phase 5: Mobile Structure (HIGH PRIORITY) 🔴
**Goal:** Make the app work well on iOS and Android

**Options to evaluate:**
1. **Progressive Web App (PWA)** - Easiest path
   - Make current web app responsive and installable
   - Service worker for offline caching
   - No app store needed, works on all devices
   - Limitation: no push notifications on iOS (without native wrapper)

2. **Capacitor/Ionic wrapper** - Web app in native shell
   - Wraps existing HTML/JS in native WebView
   - Access to native APIs (GPS, push notifications)
   - Single codebase for web + iOS + Android
   - App store distribution

3. **React Native + Expo** - Native mobile app
   - More native feel, better performance
   - Requires rewriting UI in React Native
   - expo-gl for WebGL particle rendering
   - Separate codebase from web (shared logic possible)

4. **Native Swift/Kotlin** - Maximum performance
   - 2x development effort
   - Best platform integration
   - Likely overkill for this use case

---

### Phase 6: UI/UX Improvements (MEDIUM PRIORITY) 🟡
**Goal:** Make the app visually polished and user-friendly

**Tasks:**
1. **Dark/nautical theme** - Ocean-appropriate color scheme
2. **Responsive layout** - Controls that work on mobile screens
3. **Time animation playback** - Play/pause to watch tidal cycle unfold
4. **Speed controls** - 1x, 2x, 5x, 10x time advancement
5. **Improved legend** - Gradient color bar instead of discrete blocks
6. **Loading states** - Skeleton/spinner during data fetch
7. **Location search** - Geocoding to jump to named locations
8. **Bathymetry styling** - Better depth visualization under particles

---

### Phase 7: Production Deployment (LOW PRIORITY) 🟢
**Goal:** Scalable cloud infrastructure

**Tasks:**
1. Docker containerization (multi-stage build, Python 3.11 slim)
2. AWS ECS Fargate deployment
3. CloudFront CDN for static assets
4. CI/CD pipeline (GitHub Actions)
5. Custom domain + SSL

---

### Future Enhancements (BACKLOG)
- WebGL particle rendering (regl) for 10k+ particles
- Web Workers for particle computation
- Multi-day time-series predictions
- Save favorite locations
- Push notifications for strong current events
- Integrate weather/wind data overlay
- 3D visualization (depth layers)
- Export data as CSV/GeoJSON
- Offline support (cache recently viewed regions)

---

## 12. KNOWN ISSUES & OPTIMIZATION OPPORTUNITIES

### Current Bottlenecks
1. **Element filtering in Python loop** (`currents.py:76-79`)
   - Iterates through 3.77M elements for each request
   - Could pre-compute spatial index for elements
   - Potential optimization: R-tree or grid-based element index

2. **No query result caching**
   - Same bounding box queries repeated on pan/zoom
   - Could cache recent queries (LRU cache)
   - Consider Redis for distributed caching

3. **No element LOD (Level of Detail)**
   - Always returns all triangles in bbox
   - Could simplify mesh when zoomed out
   - Reduces data transfer and rendering load

### Data Quality Notes
- **Mesh density varies greatly** (expected)
  - Coastal: 100m-1km node spacing
  - Offshore: 10km+ node spacing
- **Depth values:** Positive = below sea level (standard oceanographic convention)
- **Phase convention:** Degrees relative to constituent reference time

---

## 13. GLOSSARY

**ADCIRC** - Advanced Circulation Model (finite element ocean model)
**Constituent** - Individual tidal harmonic component (e.g., M2 = principal lunar semidiurnal)
**Barycentric coordinates** - (w0, w1, w2) weights for interpolating within triangle
**Zarr** - Chunked, compressed N-dimensional array storage format
**Nodal corrections** - Astronomical adjustments to tidal amplitudes/phases (18.6 year cycle)
**Harmonic synthesis** - Summing multiple sinusoidal components to get total signal
**Unstructured mesh** - Irregular triangulation (vs. regular grid)

**Tidal Constituents:**
- **M2** - Principal lunar semidiurnal (12.42h period) - strongest
- **S2** - Principal solar semidiurnal (12.00h)
- **N2** - Larger lunar elliptic semidiurnal (12.66h)
- **K1** - Lunisolar diurnal (23.93h)
- **O1** - Lunar diurnal (25.82h)
- **P1** - Solar diurnal (24.07h)
- **M4** - Shallow water overtide (6.21h)
- **M6** - Shallow water overtide (4.14h)

---

## 14. CONTACT & REPOSITORY

**Repository:** https://github.com/lukacatipovic/actual-currents
**Branch:** main
**SSH:** Configured and tested

---

## 15. KNOWN ISSUES & WARNINGS

1. **ttide library warnings during import:**
   ```
   RuntimeWarning: invalid value encountered in cast
   shallow_m1 = const['ishallow'].astype(int) -1
   ```
   - Internal ttide warnings, safe to ignore, do not affect prediction accuracy

2. **S3 data source not fully tested** with current MeshData pre-loading approach
   - LOCAL works perfectly, S3 `/info` endpoint confirmed working
   - Full mesh query over S3 untested with optimized code

3. **Large bounding boxes** may return too many nodes (>500k limit)
   - Zoom 8+ threshold mitigates this in practice

4. **Console logging in particles.js** is verbose (debug logs every frame)
   - Should be cleaned up before production

## 16. HOW TO RESUME DEVELOPMENT

**Step 1: Start the dev server**
```bash
cd /Users/lukacatipovic/actual-currents/backend
source tides/bin/activate
uvicorn app.main:app --reload --port 8000
```

**Step 2: Test in browser**
```
http://localhost:8000
```
- Zoom to Woods Hole, MA (lat: 41.52, lon: -70.72, zoom 9+)
- Nodes auto-load + particle animation auto-starts
- Use +1h/-1h buttons to step through tidal cycle

**Testing Locations:**
- **Woods Hole, MA** (41.52, -70.72) - Strong tidal passage, best for testing
- **NYC Harbor** (40.7, -74.0) - Complex flow patterns
- **Miami/Florida Keys** (25.2, -80.5) - Coastal currents

**Current Configuration:**
- Data source: LOCAL (`data/adcirc54.zarr`)
- Server: http://localhost:8000
- Particle params in `frontend/index.html` ~line 398: `numParticles=2500, speedScale=2, maxAge=80`

---

## 17. SESSION LOG (CONDENSED)

### 2026-02-05: Tidal Prediction API + Map Visualization
- Implemented `tidal_calc.py` harmonic synthesis with ttide
- Fixed Zarr loading bug (`consolidated=False`)
- Added velocity-colored nodes, time controls, interactive popups
- Vectorized element filtering (3000x speedup)

### 2026-02-06: Performance Optimization + Hilbert Curves
- Hilbert curve spatial ordering for optimal chunk utilization
- Direct numpy indexing replacing xarray `.where()` (6600x faster)
- MeshData RAM pre-loading (eliminates per-request Zarr I/O)
- GZip compression middleware (87% smaller responses)
- Reduced chunk size to 10k nodes, debounce to 100ms
- Query time: 6.66s → 0.017s

### 2026-02-07: Particle Animation System
- Created `frontend/js/particles.js` (622 lines)
- TriangleSpatialIndex (50x50 grid) + ParticleSystem (Canvas2D overlay)
- Barycentric interpolation, speed-based coloring (12-stop gradient)
- Pixel-space movement for zoom-independent speed
- Trail fade via `destination-in` composite
- Auto-start on data load, toggle button, pan/zoom handling

---

**End of Technical Reference**
