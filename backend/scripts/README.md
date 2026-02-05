# Data Processing Scripts

This directory contains scripts for converting and testing the ADCIRC tidal current data.

## Scripts

### convert_to_zarr.py

Converts the ADCIRC netCDF file to Zarr format with spatial chunking for fast bounding box queries.

**Features:**
- Extracts main tidal constituents (M2, S2, N2, K1, O1, P1, M4, M6)
- Spatially sorts nodes for better query performance
- Chunks data by ~50k nodes for optimal balance
- Applies Zstandard compression
- Creates consolidated metadata for fast access

**Usage:**
```bash
cd backend
source tides/bin/activate
python scripts/convert_to_zarr.py
```

**Output:**
- `data/adcirc54.zarr/` - Zarr data store

**Processing time:** ~2-5 minutes for 2M nodes

---

### test_zarr_query.py

Tests the Zarr data store with bounding box queries and demonstrates API response formatting.

**Features:**
- Tests queries for Miami, Gulf of Mexico, and New York Harbor
- Measures query performance
- Shows example API response structure
- Calculates tidal current statistics

**Usage:**
```bash
cd backend
source tides/bin/activate
python scripts/test_zarr_query.py
```

**Sample output:**
- Query times (should be <100ms for typical regions)
- Node counts per bounding box
- M2 constituent statistics
- Example JSON response format

---

## Data Flow

```
adcirc54.nc (1.8 GB)
    ↓
convert_to_zarr.py
    ↓
adcirc54.zarr/ (~1-2 GB compressed)
    ↓
test_zarr_query.py (validation)
    ↓
FastAPI endpoint (production queries)
```

## Configuration

Edit the following constants in the scripts if needed:

**convert_to_zarr.py:**
- `MAIN_CONSTITUENTS` - Which tidal constituents to extract
- `SPATIAL_CHUNK_SIZE` - Nodes per chunk (default: 50,000)

**test_zarr_query.py:**
- Bounding box coordinates for test queries
