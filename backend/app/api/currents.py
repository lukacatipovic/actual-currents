"""
Currents API endpoints - Query tidal current data for visualization
"""

from fastapi import APIRouter, HTTPException, Query
from datetime import datetime, timezone
from typing import Optional
import xarray as xr
import numpy as np
import s3fs

from ..core.tidal_calc import predict_currents
from ..core.config import get_settings

router = APIRouter()
settings = get_settings()

# Global dataset cache (loaded once)
_ds_cache = None


def get_dataset():
    """Load Zarr dataset from LOCAL or S3 (cached)"""
    global _ds_cache
    if _ds_cache is None:
        if settings.DATA_SOURCE == "LOCAL":
            # Load from local filesystem
            print(f"DEBUG: Loading Zarr from LOCAL: {settings.LOCAL_ZARR_PATH}")
            _ds_cache = xr.open_zarr(settings.LOCAL_ZARR_PATH, consolidated=False)
        else:
            # Use S3 filesystem
            s3_path = f's3://{settings.S3_BUCKET}/{settings.ZARR_PATH}'
            print(f"DEBUG: Loading Zarr from S3: {s3_path}")
            s3 = s3fs.S3FileSystem(anon=False)
            store = s3fs.S3Map(root=s3_path, s3=s3, check=False)
            _ds_cache = xr.open_zarr(store, consolidated=False)
    return _ds_cache


@router.get("/mesh")
async def get_mesh_data(
    min_lat: float = Query(..., description="Minimum latitude", ge=-90, le=90),
    max_lat: float = Query(..., description="Maximum latitude", ge=-90, le=90),
    min_lon: float = Query(..., description="Minimum longitude", ge=-180, le=180),
    max_lon: float = Query(..., description="Maximum longitude", ge=-180, le=180),
    time: Optional[str] = Query(None, description="ISO 8601 datetime (defaults to current time)")
):
    """
    Get triangular mesh data and current velocities for a bounding box

    Returns nodes, triangular elements, and predicted current velocities
    for WebGL particle animation.
    """
    try:
        import time as time_module
        start_time = time_module.time()

        # Load dataset
        print(f"DEBUG: Loading dataset...")
        ds = get_dataset()
        print(f"DEBUG: Dataset loaded in {time_module.time() - start_time:.2f}s")

        # Query nodes in bounding box
        print(f"DEBUG: Querying nodes for bbox [{min_lat}, {max_lat}] x [{min_lon}, {max_lon}]")
        lat_mask = (ds['lat'] >= min_lat) & (ds['lat'] <= max_lat)
        lon_mask = (ds['lon'] >= min_lon) & (ds['lon'] <= max_lon)
        bbox_mask = lat_mask & lon_mask

        # Get node data
        nodes_ds = ds.where(bbox_mask, drop=True)

        num_nodes = int(nodes_ds.sizes['node'])
        print(f"DEBUG: Found {num_nodes} nodes in {time_module.time() - start_time:.2f}s")

        if num_nodes == 0:
            raise HTTPException(status_code=404, detail="No nodes found in bounding box")

        if num_nodes > 500_000:
            raise HTTPException(
                status_code=400,
                detail=f"Too many nodes ({num_nodes}). Please use a smaller bounding box."
            )

        # Get node indices that are in the bounding box
        node_indices = np.where(bbox_mask.values)[0]
        node_indices_set = set(node_indices)
        print(f"DEBUG: Built node index set in {time_module.time() - start_time:.2f}s")

        # Filter elements to only those with all 3 vertices in bounding box
        # This is expensive but necessary for proper triangulation
        print(f"DEBUG: Loading elements array...")
        element_start = time_module.time()
        all_elements = ds['elements'].values
        print(f"DEBUG: Loaded {len(all_elements)} elements in {time_module.time() - element_start:.2f}s")

        # Find elements where all 3 nodes are in our node set
        # Use vectorized numpy operations instead of Python loop for massive speedup
        print(f"DEBUG: Filtering elements (vectorized)...")
        filter_start = time_module.time()

        # Check if all 3 vertices of each element are in node_indices_set
        # This vectorized approach is much faster than a Python loop
        mask_0 = np.isin(all_elements[:, 0], node_indices)
        mask_1 = np.isin(all_elements[:, 1], node_indices)
        mask_2 = np.isin(all_elements[:, 2], node_indices)
        valid_mask = mask_0 & mask_1 & mask_2

        valid_elements = all_elements[valid_mask]
        print(f"DEBUG: Filtered to {len(valid_elements)} valid elements in {time_module.time() - filter_start:.2f}s")

        # Create mapping from original node indices to new compact indices
        print(f"DEBUG: Remapping element indices...")
        remap_start = time_module.time()
        node_idx_mapping = {orig_idx: new_idx for new_idx, orig_idx in enumerate(node_indices)}

        # Remap element indices to compact 0-based indices using vectorized operations
        if len(valid_elements) > 0:
            # Vectorized remapping using numpy for speed
            elements_remapped = np.vectorize(node_idx_mapping.get)(valid_elements)
        else:
            elements_remapped = np.array([])

        print(f"DEBUG: Remapped elements in {time_module.time() - remap_start:.2f}s")

        # Extract node data
        print(f"DEBUG: Extracting node data...")
        extract_start = time_module.time()
        lats = nodes_ds['lat'].values.tolist()
        lons = nodes_ds['lon'].values.tolist()
        depths = nodes_ds['depth'].values.tolist()
        print(f"DEBUG: Extracted node arrays in {time_module.time() - extract_start:.2f}s")

        # Parse time parameter or use current time
        if time:
            try:
                prediction_time = datetime.fromisoformat(time.replace('Z', '+00:00'))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid time format: {time}. Use ISO 8601 format (e.g., 2026-02-05T12:00:00Z)")
        else:
            prediction_time = datetime.now(timezone.utc)

        print(f"DEBUG: Prediction time: {prediction_time.isoformat()}")

        # Extract constituent data for tidal prediction
        print(f"DEBUG: Extracting constituent data...")
        const_start = time_module.time()
        u_amp = nodes_ds['u_amp'].values  # Shape: (n_nodes, n_constituents)
        v_amp = nodes_ds['v_amp'].values
        u_phase = nodes_ds['u_phase'].values  # In degrees
        v_phase = nodes_ds['v_phase'].values
        tidefreqs = ds['tidefreqs'].values  # Shape: (n_constituents,)
        constituent_names = [str(name) for name in ds['constituent_names'].values]
        print(f"DEBUG: Extracted constituent arrays in {time_module.time() - const_start:.2f}s")
        print(f"DEBUG: Constituent data shapes - u_amp: {u_amp.shape}, tidefreqs: {tidefreqs.shape}")

        # Predict current velocities using harmonic synthesis
        print(f"DEBUG: Calling predict_currents()...")
        predict_start = time_module.time()
        u_vel, v_vel = predict_currents(
            u_amp=u_amp,
            v_amp=v_amp,
            u_phase=u_phase,
            v_phase=v_phase,
            tidefreqs=tidefreqs,
            constituent_names=constituent_names,
            time_utc=prediction_time,
            lat=settings.LATITUDE_FOR_NODAL
        )
        print(f"DEBUG: Tidal prediction complete in {time_module.time() - predict_start:.2f}s")
        print(f"DEBUG: Velocity stats - U: [{u_vel.min():.3f}, {u_vel.max():.3f}], V: [{v_vel.min():.3f}, {v_vel.max():.3f}]")

        # Convert numpy arrays to lists for JSON serialization
        print(f"DEBUG: Converting to JSON...")
        json_start = time_module.time()
        u_vel = u_vel.tolist()
        v_vel = v_vel.tolist()
        print(f"DEBUG: JSON conversion complete in {time_module.time() - json_start:.2f}s")

        print(f"DEBUG: TOTAL REQUEST TIME: {time_module.time() - start_time:.2f}s")

        return {
            "bbox": {
                "min_lat": min_lat,
                "max_lat": max_lat,
                "min_lon": min_lon,
                "max_lon": max_lon
            },
            "time": prediction_time.isoformat(),
            "nodes": {
                "count": num_nodes,
                "lat": lats,
                "lon": lons,
                "depth": depths,
                "u_velocity": u_vel,
                "v_velocity": v_vel
            },
            "elements": {
                "count": len(elements_remapped),
                "triangles": elements_remapped.tolist() if len(elements_remapped) > 0 else []
            },
            "constituents": [str(name) for name in nodes_ds['constituent_names'].values]
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/info")
async def get_dataset_info():
    """Get information about the dataset"""
    try:
        ds = get_dataset()

        return {
            "total_nodes": int(ds.sizes['node']),
            "total_elements": int(ds.sizes['element']),
            "constituents": [str(name) for name in ds['constituent_names'].values],
            "tide_frequencies": ds['tidefreqs'].values.tolist(),
            "lat_range": [float(ds['lat'].min().values), float(ds['lat'].max().values)],
            "lon_range": [float(ds['lon'].min().values), float(ds['lon'].max().values)],
            "depth_range": [float(ds['depth'].min().values), float(ds['depth'].max().values)]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
