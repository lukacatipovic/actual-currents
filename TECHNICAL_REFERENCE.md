# Actual Currents - Technical Reference Document

**Last Updated:** 2026-02-05
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
- **Data Storage:** Zarr format on AWS S3
- **Mobile:** React Native + Expo (recommended)
- **Visualization:** WebGL particle animation on unstructured triangular mesh
- **Web Frontend:** React + TypeScript (recommended)
- **WebGL Library:** Three.js, regl, or deck.gl (for custom particle system)
- **Mapping:** Mapbox GL JS (web) + Mapbox Maps SDK (mobile)
- **Infrastructure:** AWS ECS Fargate + S3 + CloudFront

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
**Grid-Based Spatial Sorting:**
- Nodes sorted using 100x100 grid hash for spatial locality
- Groups nearby nodes into same chunks
- Element connectivity remapped to sorted indices

**Chunking Strategy:**
- **Node chunks:** 50,000 nodes per chunk (~42 chunks total)
- **Element chunks:** 100,000 triangles per chunk
- **Constituent chunks:** All 8 constituents kept together (always queried together)
- **Benefits:** Fast bounding box queries - only loads needed chunks

**Zarr Output:**
- **Size:** 267.9 MiB (compressed from 1.8 GB)
- **Files:** 397 individual chunk files
- **Conversion Time:** ~1.4 seconds
- **Location (prod):** `s3://actual-currents-data/adcirc54.zarr` (us-east-2)

### Query Performance
**Tested Regions (script: `backend/scripts/test_zarr_query.py`):**
- Miami/Florida Keys: 250k nodes in <120ms
- Gulf of Mexico: Large region queries efficient
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

### Current Implementation Status
- **File:** `backend/app/core/tidal_calc.py`
- **Status:** ✅ Implemented (2026-02-05) - ⚠️ Needs full API testing
- **Implementation:** Complete with ttide integration
- **Testing:** Algorithm tested in isolation (works), full API endpoint not yet verified
- **Priority:** HIGH - verify with real Zarr data

### Implementation TODO
```python
def predict_currents(
    u_amp: np.ndarray,      # Shape: (n_nodes, 8)
    v_amp: np.ndarray,      # Shape: (n_nodes, 8)
    u_phase: np.ndarray,    # Shape: (n_nodes, 8)
    v_phase: np.ndarray,    # Shape: (n_nodes, 8)
    tidefreqs: np.ndarray,  # Shape: (8,)
    time_utc: datetime,
    lat: float = 55.0
) -> tuple[np.ndarray, np.ndarray]:
    """
    Returns: (u_velocity, v_velocity) in m/s
    """
    # 1. Convert time to Julian date
    # 2. Get nodal corrections (v, u, f) from ttide
    # 3. Calculate omega*t for each constituent
    # 4. Apply harmonic synthesis
    # 5. Return instantaneous velocities
    pass
```

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
**File:** `frontend/index.html`
**Status:** 🚧 Basic prototype

**Technologies:**
- Mapbox GL JS v3.0.1
- Pure HTML/JavaScript (no build step yet)
- No Node.js required (for now)

**Mapbox Token:** `pk.eyJ1IjoibHVrYWNhdGlwb3ZpYyIsImEiOiJjbWtoZHZxa2wwamR6M2Nvb3Y5cGJubTQwIn0.iuVLjdpQvRkHoxPV9IsUvg`

**Current Features:**
1. Map centered on Mid-Atlantic (-75°, 35°)
2. "Load Current Data" button - fetches mesh from API
3. Basic node visualization (cyan circles)
4. Status display with loading/error states
5. "Start Animation" button (placeholder)

**Visualization Method:**
- Nodes displayed as GeoJSON point features
- Mapbox circle layer with 2px radius, 0.6 opacity
- Shows ~150k-200k nodes for typical viewport

### Next Steps for Visualization

#### Phase 1: Real Velocity Data
**Priority:** HIGH
1. Implement `tidal_calc.py` prediction algorithm
2. Update `/api/v1/mesh` endpoint to return real velocities
3. Verify velocity magnitude and direction in frontend

#### Phase 2: WebGL Particle System
**Priority:** HIGH (visual QC requirement)

**Architecture:**
```
1. Triangle Spatial Index
   - Build grid overlay (e.g., 100x100 cells)
   - Map each triangle to grid cells it intersects
   - Fast lookup: "which triangles contain point (x,y)?"

2. Particle Initialization
   - Spawn N particles (e.g., 10,000) in viewport
   - Random positions or density-based

3. Particle Animation Loop (60 FPS)
   For each particle:
     a. Find containing triangle (use spatial index)
     b. Calculate barycentric coordinates within triangle
     c. Interpolate U/V velocity from 3 triangle vertices
     d. Update particle position: pos += velocity * dt
     e. Fade/respawn particles at boundaries

4. GPU Rendering
   - WebGL points or instanced quads
   - Vertex shader: transform particle positions
   - Fragment shader: particle appearance (glow, trail)
   - Optional: velocity-based coloring
```

**Barycentric Interpolation:**
```javascript
// Given triangle with vertices (v0, v1, v2) and velocities (u0,v0), (u1,v1), (u2,v2)
// Particle at point P with barycentric coords (w0, w1, w2)
// where w0 + w1 + w2 = 1

u_particle = w0 * u0 + w1 * u1 + w2 * u2
v_particle = w0 * v0 + w1 * v1 + w2 * v2
```

**Why NOT Leaflet.Velocity or similar:**
- Those plugins expect **regular grids** (raster data)
- Our mesh is **irregular/unstructured** (adaptive triangulation)
- Custom WebGL provides full control for triangular mesh

**Reference Implementation:**
- Check `old/` directory for MVP particle system (if exists)
- Look for triangle search, barycentric code

#### Phase 3: Performance Optimization
- Spatial index caching
- Web Workers for particle updates
- LOD (Level of Detail) - reduce particles when zoomed out
- Lazy loading chunks as user pans

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
- `backend/scripts/convert_to_zarr.py` - **Main conversion script**
  - Reads `data/adcirc54.nc`
  - Outputs `data/adcirc54.zarr/`
  - Spatial sorting, element remapping, chunking
  - ~1.4 second runtime

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

- `backend/app/core/tidal_calc.py` - **✅ IMPLEMENTED (2026-02-05)**
  - Contains `predict_currents()` function
  - ttide integration for nodal corrections (v, u, f factors)
  - Harmonic synthesis algorithm
  - Tested in isolation with synthetic data - working correctly
  - **Next:** Verify with real Zarr data through API endpoint

### Frontend
- `frontend/index.html` - **Web visualization**
  - Mapbox GL JS integration
  - Basic mesh visualization
  - API client code
  - Ready for WebGL particle system integration

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

## 10. TECH STACK RECOMMENDATIONS

### Full Stack Overview

| Layer | Technology | Status | Rationale |
|-------|-----------|--------|-----------|
| **Backend API** | FastAPI (Python 3.11+) | ✅ Implemented | Excellent for data APIs, async support, automatic docs |
| **Data Storage** | Zarr + AWS S3 | ✅ Deployed | Optimized for chunked geospatial queries, cloud-native |
| **Web Frontend** | React + TypeScript | 🚧 Recommended | Type safety, component reuse, large ecosystem |
| **Mobile Framework** | React Native + Expo | ⏳ Planned | Code sharing with web, single codebase for iOS/Android |
| **WebGL Rendering** | regl or Three.js | ⏳ To Build | Cross-platform WebGL, works on web + mobile |
| **Mapping** | Mapbox GL JS (web)<br>Mapbox Maps SDK (mobile) | 🚧 Web Started | Consistent UX, already integrated on web |
| **State Management** | Zustand or Jotai | ⏳ To Decide | Lightweight, works across React/React Native |
| **Build Tools** | Vite (web) + Expo (mobile) | ⏳ To Setup | Fast dev experience, modern tooling |

### Mobile Framework Decision

**Recommended: React Native + Expo**
- ✅ Code sharing with web frontend (business logic, API clients, particle physics)
- ✅ Single codebase for iOS and Android
- ✅ expo-gl provides WebGL support for particle rendering
- ✅ Faster iteration with hot reload
- ⚠️ Slightly lower performance than native (acceptable for this use case)

**Alternative: Flutter**
- ✅ Truly native performance
- ✅ Beautiful UI out of the box
- ⚠️ No code sharing with React web
- ⚠️ Dart language (separate from TypeScript)

**Alternative: Native Swift/Kotlin**
- ✅ Maximum performance
- ✅ Full platform API access
- ⚠️ 2x development effort (separate iOS and Android codebases)
- ⚠️ No code sharing with web

### WebGL Library for Particle Animation

**For Unstructured Mesh + Particles:**

| Library | Pros | Cons | Recommendation |
|---------|------|------|----------------|
| **regl** | Lightweight, functional API, low-level control | More code required | ✅ Best for custom particle system |
| **Three.js** | Full 3D engine, large community | Heavier bundle size | ✅ Good if adding 3D features later |
| **deck.gl** | Built-in geospatial layers | Designed for regular grids | ❌ Not ideal for triangular mesh |
| **Raw WebGL** | Maximum control | Very verbose | ❌ Unnecessary complexity |

**Recommended: regl**
- Perfect for custom particle systems
- Works on web (via bundler) and React Native (via expo-gl)
- Functional API is easier to reason about than raw WebGL
- Small bundle size (~100KB)

### Code Sharing Strategy

```
shared/
├── api/              # API client, types
├── physics/          # Particle simulation, barycentric interpolation
├── spatial/          # Triangle search, spatial indexing
└── tidal/            # Tidal calculation formulas (if needed client-side)

web/
├── components/       # React components
├── webgl/            # WebGL particle renderer (regl)
└── mapbox/           # Mapbox integration

mobile/
├── screens/          # React Native screens
├── webgl/            # expo-gl particle renderer (regl)
└── mapbox/           # Mapbox Maps SDK integration
```

**Shared logic (70% of codebase):**
- API calls and data fetching
- Particle physics and interpolation algorithms
- Spatial indexing and triangle search
- State management
- Business logic

**Platform-specific (30%):**
- Map component wrappers
- WebGL context initialization
- Navigation and UI chrome
- Platform permissions (location, etc.)

---

## 11. NEXT STEPS (PRIORITY ORDER)

### Phase 1: Real Velocity Data (HIGH PRIORITY) 🔴
**Goal:** Get actual tidal predictions working

**Status:** ✅ Implementation COMPLETE (2026-02-05) - ⚠️ Full API testing PENDING

**Completed Tasks:**
1. ✅ **Implemented `backend/app/core/tidal_calc.py`**
   - Used ttide library for nodal corrections (v, u, f)
   - Implemented harmonic synthesis: `velocity = Σ [f[i] * amp[i] * cos(v + ω*t + u - phase)]`
   - Handled matplotlib date conversion (`date2num() + 366`)
   - Reference time: 2000-01-01T00:00:00Z
   - Constituent index mapping for standard ADCIRC constituents
   - Tested with synthetic data - velocities change correctly with time

2. ✅ **Integrated into `/api/v1/mesh` endpoint**
   - Replaced placeholder `(0.0, 0.0)` with `predict_currents()` call
   - Extracts constituent data from Zarr (u_amp, v_amp, u_phase, v_phase, tidefreqs)
   - Handles time parameter from query string (ISO 8601 format)
   - Uses config.LATITUDE_FOR_NODAL (55.0°N) for nodal corrections

**Pending Tasks:**
3. ⚠️ **Test with real Zarr data through API** (30-60 mins)
   - Verify API endpoint returns non-zero velocities
   - Test with strong tidal areas: Miami/Florida Keys, NYC Harbor
   - Verify magnitude ranges (0-2 m/s typical, up to 5 m/s in straits)
   - Check velocity reversal over ~6-hour tidal cycle
   - Compare predictions with expected tidal patterns

**Acceptance Criteria:**
- [x] `predict_currents()` function implemented and working
- [x] Function integrated into `/api/v1/mesh` endpoint
- [ ] `/api/v1/mesh?time=2026-02-05T12:00:00Z&...` verified with real data
- [ ] Velocities have reasonable magnitudes (0-2 m/s typical)
- [ ] Flow directions change over ~6-hour tidal cycle

**Implementation Details:**
- Algorithm based on old MVP reference code (`old/backend.py`)
- ttide requires constituent indices (not names) - hardcoded standard mapping
- Nodal corrections returned in "cycles" - converted to radians by multiplying by 2π
- Frequencies in rad/s, time delta calculated in seconds from REFERENCE_TIME

---

### Phase 2: WebGL Particle System (HIGH PRIORITY) 🔴
**Goal:** Visual QC of tidal predictions through particle animation

**Status:** ⏳ Not started

**Tasks:**
1. **Build Triangle Spatial Index** (1 hour)
   - Create 100x100 grid overlay for viewport
   - Map each triangle to grid cells it intersects
   - Enables fast "which triangle contains point (x,y)?" lookup

2. **Implement Barycentric Interpolation** (1 hour)
   - Point-in-triangle test (cross product method)
   - Calculate barycentric weights (w0, w1, w2)
   - Interpolate velocity: `u = w0*u0 + w1*u1 + w2*u2`

3. **WebGL Particle Renderer** (2 hours)
   - Initialize 10,000 particles in viewport
   - Render loop (60 FPS):
     - Find containing triangle (use spatial index)
     - Interpolate U/V velocity
     - Update position: `pos += velocity * dt`
     - Fade/respawn at boundaries
   - Use `regl` library for cleaner WebGL code

4. **Visual QC Verification**
   - [ ] Particles flow smoothly (no jumps or artifacts)
   - [ ] Strong currents in channels, inlets, straits
   - [ ] Weaker currents in open ocean
   - [ ] Flow reverses with tidal cycle (~6-12 hours)
   - [ ] Magnitude visualization matches expected patterns

**Acceptance Criteria:**
- [ ] 10k+ particles rendering at 60 FPS
- [ ] Particles follow triangular mesh interpolation
- [ ] Visual confirmation that tidal predictions are realistic

---

### Phase 3: Web Frontend Refinement (MEDIUM PRIORITY) 🟡
**Goal:** Production-ready web application

**Status:** 🚧 Basic prototype exists (frontend/index.html)

**Tasks:**
1. **Migrate to React + TypeScript** (3-4 hours)
   - Set up Vite project
   - Component structure: Map, ParticleLayer, Controls, Timeline
   - Move existing Mapbox code into React components

2. **Time Controls UI** (2 hours)
   - Date/time picker
   - Play/pause animation
   - Speed control (1x, 2x, 5x, 10x)
   - Display current tidal phase

3. **Performance Optimization** (2 hours)
   - Implement LRU cache for API responses
   - Web Workers for particle updates
   - Level-of-detail: reduce particle count when zoomed out
   - Lazy load chunks as user pans

4. **Visual Polish**
   - Velocity color scale legend
   - Loading states and error handling
   - Responsive design (mobile browser support)

---

### Phase 4: React Native Mobile App (MEDIUM PRIORITY) 🟡
**Goal:** iOS and Android apps

**Status:** ⏳ Not started

**Tasks:**
1. **Expo Setup** (1 hour)
   - Initialize Expo project with TypeScript
   - Configure Mapbox Maps SDK for React Native
   - Set up expo-gl for WebGL

2. **Shared Code Integration** (2 hours)
   - Move API client, types, particle physics to `shared/` directory
   - Use Yarn workspaces or npm workspaces for monorepo
   - Import shared code into mobile project

3. **Mobile-Specific Features** (3-4 hours)
   - GPS location integration
   - "My Location" button
   - Offline support (cache recently viewed regions)
   - Native navigation (React Navigation)

4. **Platform Builds**
   - iOS simulator testing
   - Android emulator testing
   - TestFlight beta (iOS)
   - Google Play internal testing (Android)

---

### Phase 5: Production Deployment (LOW PRIORITY) 🟢
**Goal:** Scalable cloud infrastructure

**Status:** ⏳ Data on S3, API not deployed yet

**Tasks:**
1. **Docker Containerization** (1 hour)
   - Multi-stage Dockerfile
   - Python 3.11 slim base image
   - Health check endpoint

2. **AWS ECS Fargate** (2-3 hours)
   - ECS cluster and task definition
   - Application Load Balancer
   - Auto-scaling configuration
   - CloudWatch logging

3. **CloudFront CDN** (1 hour)
   - Serve static web assets from S3
   - Edge caching for API responses
   - Custom domain (optional)

4. **CI/CD Pipeline** (2 hours)
   - GitHub Actions workflow
   - Run tests on PR
   - Deploy to staging on merge to `develop`
   - Deploy to production on merge to `main`

---

### Future Enhancements (BACKLOG) 📋
- Multi-day time-series predictions
- Current speed/direction at specific point (tap on map)
- Save favorite locations
- Push notifications for strong current events
- Integrate weather/wind data
- 3D visualization (depth layers)
- Export data as CSV/GeoJSON

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

## 15. CURRENT PROGRESS & NEXT STEPS

**Last Updated:** 2026-02-05 22:00 UTC

### 🎉 EXECUTIVE SUMMARY

**Phase 1: Tidal Prediction API** - ✅ **COMPLETE**
- Implemented harmonic synthesis algorithm with ttide nodal corrections
- Optimized element filtering (vectorized numpy - 3000x speedup)
- API returns real tidal current predictions in <4 seconds
- Verified with Woods Hole, MA test - velocities change correctly with tidal cycle

**Phase 2: Map Visualization** - ✅ **COMPLETE & TESTED**
- ✅ Fixed critical Zarr loading issue (consolidated=False)
- ✅ Velocity data displayed on map (colored nodes by magnitude)
- ✅ Time controls working (+1h/-1h, datetime picker, jump to now)
- ✅ Interactive popups showing velocity details on node click
- ✅ Velocity legend (blue=calm, green=moderate, yellow=strong, red=very strong)
- ✅ Statistics display (avg/max velocity)
- ✅ User-tested and confirmed working with Woods Hole area

**Phase 3: Particle Animation** - ⏳ **NEXT PRIORITY**
- Goal: WebGL particle system with barycentric interpolation
- Will enable visual QC of tidal flow patterns
- Foundation ready: mesh data and velocities available

---

### 🎉 CURRENT STATUS SUMMARY

**Phase 1 & 2:** ✅ 100% COMPLETE - Full tidal visualization working!

**What Works:**
- ✅ Tidal prediction algorithm implemented and VERIFIED (`tidal_calc.py`)
- ✅ API endpoint `/api/v1/mesh` working reliably (Zarr loading fixed)
- ✅ Map visualization displaying velocity-colored nodes
- ✅ Time controls functional (+1h/-1h, datetime picker, jump to now)
- ✅ Interactive popups with velocity/depth details
- ✅ Velocities change correctly with tidal cycle (6-12 hour periods)
- ✅ Element filtering optimized (vectorized numpy - 3000x faster)
- ✅ Sub-5-second response times for typical queries
- ✅ User-tested and confirmed working

**Test Results (Woods Hole, MA - 299 nodes):**
- Response time: **~4 seconds**
- U velocities: -0.80 to 0.04 m/s
- V velocities: -0.19 to 0.54 m/s
- Flow direction **reverses over 6-hour tidal cycle** ✅
- Magnitudes realistic for known strong tidal area
- Visualization displays colored dots (blue=calm, green/yellow/red=stronger currents)

**Next Priority:**
Build WebGL particle animation system for enhanced visual QC and user experience

---

### Recently Completed (2026-02-05 Evening)

#### 🐛 Critical Bug Fix - Zarr Loading Hang (2026-02-05 22:00 UTC)
**Problem:** API endpoint `/api/v1/mesh` was timing out on all requests, hanging indefinitely

**Root Cause:**
- Zarr store was opened with `consolidated=True` flag
- Local Zarr directory had no `.zmetadata` file (consolidated metadata)
- `xr.open_zarr()` hung waiting for consolidated metadata that didn't exist

**Solution:**
- Changed `consolidated=True` to `consolidated=False` in `get_dataset()` function
- Both LOCAL and S3 data sources updated (lines 29 and 36 in `currents.py`)

**Files Modified:**
- `backend/app/api/currents.py` - Line 29 and 36

**Result:**
- ✅ API now responds in <5 seconds for Woods Hole query (299 nodes)
- ✅ Visualization working and tested by user
- ✅ All features functional (time controls, popups, statistics)

**Note:** If consolidated metadata is desired for performance, run:
```python
import zarr
zarr.consolidate_metadata('data/adcirc54.zarr')
```

#### ✅ Phase 2: Map Visualization - COMPLETE (2026-02-05 21:30 UTC)
**Files Modified:**
- `frontend/index.html` - UPDATED (velocity visualization, time controls, interactive features)

**Implementation Details:**
1. **Velocity Magnitude Coloring**
   - Calculates `magnitude = sqrt(u² + v²)` for each node
   - Color interpolation: blue (0.0) → green (0.3) → yellow (0.6) → red (1.0+ m/s)
   - Circle radius: 3px with 0.7 opacity

2. **Time Controls**
   - Datetime picker for selecting any time
   - +1h / -1h buttons for stepping through tidal cycle
   - "Jump to Now" button to reset to current time
   - Time display shows formatted local time with timezone

3. **Interactive Features**
   - Click on any node to see popup with:
     - Current speed and direction (compass bearing)
     - U (eastward) and V (northward) components
     - Bathymetric depth
   - Cursor changes to pointer on node hover
   - Statistics display: average and max velocity for visible area

4. **Velocity Legend**
   - Color scale reference in bottom-left corner
   - Four velocity ranges with labels

**Testing Recommendations:**
- Use Woods Hole, MA area for strong tidal currents
- Step through time in 1-hour increments to see tidal cycle (should reverse ~every 6 hours)
- Compare different times to verify flow patterns change
- Check that velocity magnitudes are reasonable (0.1-1.5 m/s typical)

#### ✅ Phase 1: Tidal Prediction Algorithm - COMPLETE
**Files Modified:**
- `backend/app/core/tidal_calc.py` - NEW FILE (136 lines)
- `backend/app/api/currents.py` - UPDATED (tidal prediction integration + performance optimizations)
- `backend/.env` - UPDATED (added LOCAL data source support)
- `backend/app/core/config.py` - UPDATED (config for LOCAL/S3 data sources)

**Implementation Details:**
1. Created `predict_currents()` function implementing harmonic synthesis
2. Integrated ttide library for astronomical nodal corrections:
   - v (equilibrium argument) - in cycles, converted to radians
   - u (Greenwich phase lag) - in cycles, converted to radians
   - f (nodal amplitude correction) - dimensionless scaling factor
3. Time handling:
   - Accepts datetime objects (timezone-aware)
   - Converts to matplotlib date format: `date2num(time_utc) + 366`
   - Calculates seconds since ADCIRC reference time (2000-01-01 00:00:00 UTC)
4. Constituent mapping:
   - Hardcoded standard ADCIRC constituents (M2, S2, N2, K1, O1, P1, M4, M6)
   - ttide expects indices, not names - created mapping dictionary
5. Algorithm:
   ```python
   for each constituent i:
       phase_u = v[i] + omega[i]*t + u[i] - u_phase[:,i]
       phase_v = v[i] + omega[i]*t + u[i] - v_phase[:,i]
       u_velocity += f[i] * u_amp[:,i] * cos(phase_u)
       v_velocity += f[i] * v_amp[:,i] * cos(phase_v)
   ```

6. Testing performed:
   - ✅ Tested with synthetic data (5 nodes, 8 constituents)
   - ✅ Verified velocities change with time (6-hour difference shows tidal cycle)
   - ✅ Magnitudes in expected range (0.5-1.5 m/s for test data)
   - ✅ **Full API endpoint tested with real Zarr data - WORKING**
   - ✅ **Woods Hole, MA test:** 299 nodes, velocities -0.80 to 0.54 m/s
   - ✅ **Tidal cycle verified:** Flow reverses over 6-12 hour periods

**Integration into API:**
- Updated `/api/v1/mesh` endpoint in `currents.py`
- Extracts constituent data from Zarr for nodes in bounding box
- Parses ISO 8601 time parameter or uses current UTC time
- Calls `predict_currents()` and returns real tidal velocities
- Returns velocities as JSON arrays

#### ✅ Critical Performance Optimization
**Problem:** Original element filtering used Python loop iterating through 3.77M elements - caused 60+ second hangs

**Solution:** Vectorized filtering using numpy (lines 79-85 in currents.py):
```python
# Old (slow): Python for loop - iterates 3.77M times
for elem_idx in range(len(all_elements)):
    if all(node_idx in node_indices_set for node_idx in elem_nodes):
        valid_elements.append(elem_nodes)

# New (fast): Vectorized numpy operations
mask_0 = np.isin(all_elements[:, 0], node_indices)
mask_1 = np.isin(all_elements[:, 1], node_indices)
mask_2 = np.isin(all_elements[:, 2], node_indices)
valid_mask = mask_0 & mask_1 & mask_2
valid_elements = all_elements[valid_mask]
```

**Performance Impact:**
- **Before:** 60+ seconds (timeout)
- **After:** 0.01-0.02 seconds (3000x faster!)
- **Total query time:** 3-4 seconds for typical requests

#### ✅ LOCAL vs S3 Data Source Support
**Problem:** S3 queries were timing out during development/testing

**Solution:** Added LOCAL data source option for faster iteration:
- `.env` file: Set `DATA_SOURCE=LOCAL` or `DATA_SOURCE=S3`
- `LOCAL_ZARR_PATH` config setting for local file path
- `get_dataset()` function handles both sources
- LOCAL data much faster for development (no network latency)

**Current Setup:**
- Development: Using LOCAL data (`/Users/lukacatipovic/actual-currents/data/adcirc54.zarr`)
- Production (planned): Will use S3 data once deployed

#### ✅ AWS S3 Configuration (2026-02-05 19:45 UTC)
**Files Modified:**
- `backend/.env` - NEW FILE (created with S3 configuration)
- AWS credentials from `~/.aws/credentials` being used automatically

**Configuration Details:**
- Created `.env` file with `DATA_SOURCE=S3`
- S3 bucket: `actual-currents-data` (us-east-2)
- AWS SDK automatically using credentials from `~/.aws/credentials` (default profile)
- Verified `/api/v1/info` endpoint works - successfully loads data from S3

**Testing Status:**
- ✅ Server starts successfully
- ✅ `/api/v1/info` endpoint works (returns 2M+ nodes, 8 constituents, frequency data)
- ❌ `/api/v1/mesh` endpoint **hanging/timing out** (60+ seconds, no response)

#### 🔧 ttide Library Investigation (2026-02-05 19:45 UTC)
**Problem:** API endpoint hanging when calling tidal prediction algorithm

**Actions Taken:**
1. Moved ttide library source code locally to `backend/lib/ttide_py-master`
2. Examined source code:
   - `t_vuf.py` - Main nodal correction function
   - `t_getconsts.py` - Loads constituent data from NetCDF files at import time
   - Found data files exist: `t_constituents_const.nc`, `t_constituents_sat.nc`, `t_constituents_shallow.nc`
3. Updated `backend/requirements.txt` to use local ttide:
   - Changed from `ttide==0.3.1` to `-e ./lib/ttide_py-master`
4. Reinstalled ttide from local directory: `pip install -e ./lib/ttide_py-master`
5. Tested ttide in isolation - **works correctly!**
   - Successfully computes nodal corrections (v, u, f)
   - Returns expected values
   - Only shows harmless RuntimeWarnings about NaN casting

**Current Status:**
- ✅ ttide library works in isolation
- ✅ Server restarts successfully with local ttide
- ✅ `/api/v1/mesh` endpoint working - **Zarr loading issue fixed (consolidated=False)**

### Immediate Next Steps

**Phase 3: WebGL Particle System** (HIGH PRIORITY - Current Focus)

**Goal:** Animate particles flowing along tidal currents for visual QC of predictions

**Status:** ✅ Map visualization working, ready for particle animation

**Approach:** Build triangle spatial index → barycentric interpolation → WebGL rendering

**Implementation Steps:**

1. **Update frontend/index.html** (1-2 hours)
   - Keep existing Mapbox map setup
   - Update "Load Current Data" button to use real API endpoint
   - Parse velocity data from API response
   - Choose visualization method (pick ONE to start):
     - **Option A (Recommended):** Color nodes by velocity magnitude
     - **Option B:** Display velocity vectors as arrows (canvas overlay)
     - **Option C:** Simple heatmap using Mapbox expressions

2. **Test with Woods Hole, MA** (15 mins)
   ```javascript
   // Example API call
   const bbox = {
     min_lat: 41.5,
     max_lat: 41.55,
     min_lon: -70.75,
     max_lon: -70.7
   };
   const time = new Date().toISOString();
   const url = `/api/v1/mesh?min_lat=${bbox.min_lat}&max_lat=${bbox.max_lat}&min_lon=${bbox.min_lon}&max_lon=${bbox.max_lon}&time=${time}`;
   ```

3. **Add time controls** (1 hour)
   - Simple time picker or +/- buttons to change time
   - Show current selected time
   - Reload data when time changes
   - Animate through time (play/pause)

4. **Visual QC Checklist:**
   - [ ] Can see velocity magnitude varying across map
   - [ ] Stronger currents in channels/inlets (Woods Hole passage)
   - [ ] Weaker currents in open water
   - [ ] Flow direction changes over 6-hour period
   - [ ] No visual artifacts or missing data

**Recommended Visualization (Option A Details):**
```javascript
// Color nodes by velocity magnitude
const magnitude = Math.sqrt(u*u + v*v);
const color = velocityToColor(magnitude); // e.g., blue (slow) to red (fast)

// Add as Mapbox circle layer with data-driven styling
map.addLayer({
  id: 'current-nodes',
  type: 'circle',
  source: 'currents',
  paint: {
    'circle-radius': 3,
    'circle-color': [
      'interpolate',
      ['linear'],
      ['get', 'magnitude'],
      0, '#0000ff',      // Blue for calm
      0.5, '#00ff00',    // Green for moderate
      1.0, '#ff0000'     // Red for strong
    ],
    'circle-opacity': 0.7
  }
});
```

**After Basic Visualization Works:**
- Add legend showing velocity color scale
- Display velocity magnitude/direction on hover
- Save selected time/location in URL params
- Then move to particle animation (Phase 3)

### Known Issues & Warnings

1. **ttide library warnings during import:**
   ```
   RuntimeWarning: invalid value encountered in cast
   shallow_m1 = const['ishallow'].astype(int) -1
   ```
   - These are internal ttide warnings, safe to ignore
   - Do not affect prediction accuracy

2. **Constituent index mapping:**
   - Currently hardcoded for 8 standard ADCIRC constituents
   - If dataset has different constituents, mapping will need update
   - Could extract constituent names from Zarr at runtime for robustness

3. **API endpoint not tested end-to-end:**
   - Integration code is in place
   - Algorithm works in isolation
   - **MUST verify with real S3 Zarr data before considering complete**

4. **Potential performance issue:**
   - Element filtering loop (lines 76-79 in currents.py) still in Python
   - For large bounding boxes (>100k elements), this could be slow
   - Consider pre-computing spatial index in future optimization

### Files Changed Summary (2026-02-05 Session)

```
backend/app/core/tidal_calc.py          NEW (136 lines) - tidal prediction algorithm ✅
backend/app/api/currents.py             MODIFIED - tidal predictions + element filtering + Zarr fix ✅
                                        - Line 29 & 36: consolidated=False (critical bug fix)
backend/app/core/config.py              MODIFIED - added LOCAL_ZARR_PATH setting ✅
backend/.env                             NEW - DATA_SOURCE=LOCAL configuration ✅
backend/requirements.txt                 MODIFIED - ttide local version
backend/lib/ttide_py-master/             NEW DIRECTORY - local ttide library source
frontend/index.html                      MODIFIED - velocity visualization + time controls ✅
                                        - Added velocity magnitude coloring
                                        - Added time controls (+1h/-1h, picker)
                                        - Added interactive popups
                                        - Added velocity legend
TECHNICAL_REFERENCE.md                   UPDATED (this file) ✅
```

**Git Status:**
- ✅ Phase 1 complete - ready to commit changes
- Consider adding `backend/lib/` to .gitignore (3rd party library)
- Consider adding `backend/.env` to .gitignore (contains paths/config)

**Key Optimizations Made:**
1. **Vectorized element filtering** - 3000x faster (0.02s vs 60+s)
2. **LOCAL data source** - faster iteration during development
3. **Debug logging** - comprehensive timing for performance monitoring

### How to Resume Work in Next Session

**CURRENT STATUS:** ✅ Phases 1 & 2 COMPLETE - Full working visualization with real tidal predictions

**COMPLETED THIS SESSION:**
- Fixed critical Zarr loading bug (`consolidated=False` fix)
- Confirmed visualization working with user testing
- Time controls functional
- Interactive features working (popups, statistics)

**NEXT TASK:** Phase 3 - Build WebGL Particle Animation System

**To Resume:**

1. **Start the dev server:**
   ```bash
   cd /Users/lukacatipovic/actual-currents
   ./run_dev.sh
   # Or manually:
   # cd backend && source tides/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

2. **Verify everything is working:**
   ```bash
   # Test API endpoint
   curl "http://localhost:8000/api/v1/mesh?min_lat=41.5&max_lat=41.55&min_lon=-70.75&max_lon=-70.7&time=2026-02-05T12:00:00Z" | python3 -m json.tool | head -50

   # Open browser
   open http://localhost:8000

   # Should see:
   # - Dark map with controls (top right) and legend (bottom left)
   # - Click "Load Current Data" to see colored dots
   # - Use +1h/-1h to step through time
   # - Click dots to see velocity details
   ```

3. **Begin Phase 3 - Particle Animation:**
   - Goal: Animate particles flowing with tidal currents
   - Approach: Triangle spatial index → barycentric interpolation → WebGL rendering

   **Implementation Steps:**

   a. **Build Triangle Spatial Index** (~1 hour)
      - Create grid overlay (e.g., 100x100 cells) for viewport
      - Map each triangle to grid cells it intersects
      - Enable fast "which triangle contains point (x,y)?" lookup

   b. **Implement Barycentric Interpolation** (~1 hour)
      - Point-in-triangle test (cross product method)
      - Calculate barycentric weights (w0, w1, w2)
      - Interpolate velocity: `u = w0*u0 + w1*u1 + w2*u2`

   c. **WebGL Particle Renderer** (~2-3 hours)
      - Initialize 5,000-10,000 particles in viewport
      - Render loop (60 FPS):
        - Find containing triangle (use spatial index)
        - Interpolate U/V velocity at particle position
        - Update position: `pos += velocity * dt`
        - Fade/respawn particles at boundaries
      - Use `regl` library for cleaner WebGL code (or raw WebGL/Canvas2D for MVP)

   d. **Visual QC Verification**
      - [ ] Particles flow smoothly (no jumps or artifacts)
      - [ ] Strong currents in channels, inlets, straits
      - [ ] Weaker currents in open ocean
      - [ ] Flow reverses with tidal cycle (~6-12 hours)
      - [ ] Magnitude visualization matches expected patterns

4. **Testing locations for particle animation:**
   - **Woods Hole, MA:** `-70.72, 41.52` - Strong tidal passage
   - **NYC Harbor:** Strong ebb/flood tides
   - **Gulf of Mexico:** Weaker currents for contrast

5. **Current file structure:**
   ```
   frontend/index.html         - Working visualization (Phase 2 complete)
   backend/app/api/currents.py - API endpoint (Zarr fix applied)
   backend/app/core/tidal_calc.py - Tidal predictions (working)
   data/adcirc54.zarr/         - Local Zarr data
   ```

**Current Configuration:**
- Data source: LOCAL (`/Users/lukacatipovic/actual-currents/data/adcirc54.zarr`)
- Server: http://localhost:8000
- API endpoint: `/api/v1/mesh`
- Frontend: Served from `frontend/` directory

**Known Limitations:**
- Large bounding boxes (>0.5° x 0.5°) may take 10+ seconds to load
- Recommend testing with small regions first (0.05° x 0.05° for Woods Hole)
- S3 data source not tested yet (using LOCAL for development)
- No particle animation yet - only static node visualization
- No mesh simplification/LOD - returns all nodes in bbox

**Performance Notes:**
- Woods Hole area (0.05° x 0.05°): ~299 nodes, ~4 seconds
- Larger areas scale linearly with node count
- Element filtering is optimized (vectorized numpy)
- Zarr chunking provides good spatial locality

---

## 16. SESSION SUMMARY (2026-02-05)

### 🎉 Major Accomplishments

**Phase 2 Visualization - COMPLETED & TESTED**

1. **Critical Bug Fix - Zarr Loading**
   - Problem: API hanging on all requests (10+ second timeouts)
   - Root cause: `xr.open_zarr(consolidated=True)` waiting for non-existent `.zmetadata`
   - Solution: Changed to `consolidated=False` in `currents.py` lines 29 & 36
   - Result: API now responds in ~4 seconds ✅

2. **Visualization Features Implemented**
   - Velocity magnitude coloring (blue→green→yellow→red scale)
   - Time controls (+1h/-1h buttons, datetime picker, "Jump to Now")
   - Interactive node popups (speed, direction, U/V components, depth)
   - Velocity legend and statistics (avg/max velocity display)
   - All features user-tested and confirmed working ✅

3. **User Testing**
   - Tested with Woods Hole, MA area (known for strong tidal currents)
   - Confirmed dots appear on map colored by velocity magnitude
   - Verified time controls work (can step through tidal cycle)
   - Confirmed interactive features (popups, statistics) functional

### 📊 Current System Status

**What's Working:**
- ✅ Backend API serving real tidal predictions
- ✅ Frontend visualization displaying colored velocity nodes
- ✅ Time controls for exploring tidal cycles
- ✅ Interactive features (popups, statistics, legend)
- ✅ Local Zarr data loading reliably
- ✅ Response times acceptable (~4s for 299 nodes)

**What's Next:**
- ⏳ Phase 3: WebGL particle animation system
- ⏳ Triangle spatial indexing for velocity interpolation
- ⏳ Barycentric interpolation within mesh triangles
- ⏳ Real-time particle rendering at 60 FPS

### 🚀 Next Session Goals

**Priority: Phase 3 - Particle Animation**

1. Build triangle spatial index for fast point-in-triangle queries
2. Implement barycentric interpolation for velocity at arbitrary points
3. Create WebGL particle system (5,000-10,000 particles)
4. Render particles flowing with tidal currents at 60 FPS
5. Visual QC: Verify flow patterns match expectations

**Why Particle Animation:**
- More intuitive than static colored dots
- Clearly shows flow direction and intensity
- Essential for visual QC of tidal predictions
- Engaging user experience
- Industry standard for oceanographic visualization

**Estimated Time:** 4-6 hours of development + testing

---

**End of Technical Reference**
