# Actual Currents

Real-time tidal current visualization app for iOS and Android.

## Project Overview

High-resolution tidal current predictions for the Western North Atlantic using ADCIRC harmonic constituent data.

**Coverage:** Gulf of Mexico to Nova Scotia (5.7°N - 45.9°N, 98°W - 54°W)
**Resolution:** Adaptive triangular mesh (2M+ nodes, denser in coastal areas)
**Data Source:** NOAA ADCIRC tidal constituent harmonics

## Architecture

- **Backend:** FastAPI (Python 3.11)
- **Data:** Zarr format with spatial chunking (fast bounding box queries)
- **Frontend:** React Native (iOS/Android)
- **Visualization:** WebGL particle animations on irregular mesh
- **Deployment:** AWS (ECS Fargate + S3)

## Project Structure

```
actual-currents/
├── backend/
│   ├── app/              # FastAPI application
│   ├── scripts/          # Data processing scripts
│   └── requirements.txt
├── frontend/             # React Native app (TBD)
├── data/                 # Zarr data store (local dev)
├── old/                  # MVP reference code
└── docs/                 # Documentation
```

## Development Setup

### Backend

```bash
cd backend
python3 -m venv tides
source tides/bin/activate
pip install -r requirements.txt
```

### Data Processing

```bash
# Convert netCDF to Zarr (one-time)
python backend/scripts/convert_to_zarr.py

# Test spatial queries
python backend/scripts/test_zarr_query.py

# Visualize data
python backend/scripts/plot_zarr_data.py
```

## Status

**Phase 1: Data Processing** ✅ Complete
- [x] NetCDF → Zarr conversion with spatial chunking
- [x] Fast bounding box queries (<120ms for 250k nodes)
- [x] Visualization validation

**Phase 2: API Development** 🚧 In Progress
- [ ] FastAPI endpoint with tidal prediction algorithm
- [ ] S3 integration for Zarr data
- [ ] Time-series prediction
- [ ] Docker containerization

**Phase 3: Mobile App** 📋 Planned
- [ ] React Native setup
- [ ] WebGL particle renderer
- [ ] Map integration

**Phase 4: Deployment** 📋 Planned
- [ ] AWS ECS Fargate
- [ ] S3 for Zarr storage
- [ ] CloudFront CDN
- [ ] CI/CD pipeline

## Features

- 🌊 Real-time tidal current predictions
- 📱 Native mobile experience (iOS/Android)
- 🎨 WebGL particle flow visualization
- 🗺️ Irregular mesh preserves coastal detail
- ⚡ Fast spatial queries with Zarr chunking
- 🌍 8 main tidal constituents (M2, S2, N2, K1, O1, P1, M4, M6)

## License

TBD

## Data Attribution

NOAA/NOS/OCS/CSDL/MMAP - ADCIRC Western North Atlantic Model
