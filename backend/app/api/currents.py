"""
Currents API endpoints - Query tidal current data for visualization
"""

from fastapi import APIRouter, HTTPException, Query
from datetime import datetime, timezone
from typing import Optional
import xarray as xr
import numpy as np
import s3fs
import time as time_module

from ..core.tidal_calc import predict_currents
from ..core.config import get_settings

router = APIRouter()
settings = get_settings()


# Pre-loaded numpy arrays (loaded once at startup, held in RAM)
class MeshData:
    """All static mesh data pre-loaded into numpy arrays for fast access."""
    lat: np.ndarray = None
    lon: np.ndarray = None
    depth: np.ndarray = None
    elements: np.ndarray = None
    u_amp: np.ndarray = None
    v_amp: np.ndarray = None
    u_phase: np.ndarray = None
    v_phase: np.ndarray = None
    tidefreqs: np.ndarray = None
    constituent_names: list = None
    loaded: bool = False


_mesh = MeshData()


def _load_mesh_data():
    """Load all static arrays from Zarr into RAM (called once at startup)."""
    if _mesh.loaded:
        return

    load_start = time_module.time()

    if settings.DATA_SOURCE == "LOCAL":
        print(f"Loading Zarr from LOCAL: {settings.LOCAL_ZARR_PATH}")
        ds = xr.open_zarr(settings.LOCAL_ZARR_PATH, consolidated=False)
    else:
        s3_path = f's3://{settings.S3_BUCKET}/{settings.ZARR_PATH}'
        print(f"Loading Zarr from S3: {s3_path}")
        s3 = s3fs.S3FileSystem(anon=False)
        store = s3fs.S3Map(root=s3_path, s3=s3, check=False)
        ds = xr.open_zarr(store, consolidated=False)

    # Pull everything into numpy arrays (one-time cost)
    _mesh.lat = ds['lat'].values
    _mesh.lon = ds['lon'].values
    _mesh.depth = ds['depth'].values
    _mesh.elements = ds['elements'].values
    _mesh.u_amp = ds['u_amp'].values
    _mesh.v_amp = ds['v_amp'].values
    _mesh.u_phase = ds['u_phase'].values
    _mesh.v_phase = ds['v_phase'].values
    _mesh.tidefreqs = ds['tidefreqs'].values
    _mesh.constituent_names = [str(name) for name in ds['constituent_names'].values]
    _mesh.loaded = True

    elapsed = time_module.time() - load_start
    print(f"Mesh data loaded into RAM in {elapsed:.2f}s "
          f"({len(_mesh.lat)} nodes, {len(_mesh.elements)} elements, "
          f"{len(_mesh.constituent_names)} constituents)")


@router.get("/mesh")
async def get_mesh_data(
    min_lat: float = Query(..., description="Minimum latitude", ge=-90, le=90),
    max_lat: float = Query(..., description="Maximum latitude", ge=-90, le=90),
    min_lon: float = Query(..., description="Minimum longitude", ge=-180, le=180),
    max_lon: float = Query(..., description="Maximum longitude", ge=-180, le=180),
    time: Optional[str] = Query(None, description="ISO 8601 datetime (defaults to current time)"),
    include_elements: bool = Query(True, description="Include triangle elements in response"),
    include_depth: bool = Query(True, description="Include depth data in response")
):
    """
    Get triangular mesh data and current velocities for a bounding box.

    Returns nodes, triangular elements, and predicted current velocities
    for WebGL particle animation.
    """
    try:
        start_time = time_module.time()

        # Ensure data is loaded
        _load_mesh_data()

        # Query nodes in bounding box (pure numpy — microseconds)
        bbox_mask = (
            (_mesh.lat >= min_lat) & (_mesh.lat <= max_lat) &
            (_mesh.lon >= min_lon) & (_mesh.lon <= max_lon)
        )
        node_indices = np.where(bbox_mask)[0]
        num_nodes = len(node_indices)

        if num_nodes == 0:
            raise HTTPException(status_code=404, detail="No nodes found in bounding box")

        if num_nodes > 500_000:
            raise HTTPException(
                status_code=400,
                detail=f"Too many nodes ({num_nodes}). Please use a smaller bounding box."
            )

        # Extract node positions (direct numpy slicing on RAM arrays)
        lats = _mesh.lat[node_indices]
        lons = _mesh.lon[node_indices]

        # Parse time parameter
        if time:
            try:
                prediction_time = datetime.fromisoformat(time.replace('Z', '+00:00'))
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid time format: {time}. Use ISO 8601 format (e.g., 2026-02-05T12:00:00Z)"
                )
        else:
            prediction_time = datetime.now(timezone.utc)

        # Extract constituent data and predict velocities (numpy slicing — fast)
        u_vel, v_vel = predict_currents(
            u_amp=_mesh.u_amp[node_indices, :],
            v_amp=_mesh.v_amp[node_indices, :],
            u_phase=_mesh.u_phase[node_indices, :],
            v_phase=_mesh.v_phase[node_indices, :],
            tidefreqs=_mesh.tidefreqs,
            constituent_names=_mesh.constituent_names,
            time_utc=prediction_time,
            lat=settings.LATITUDE_FOR_NODAL
        )

        # Build response
        response = {
            "time": prediction_time.isoformat(),
            "nodes": {
                "count": num_nodes,
                "lat": lats.tolist(),
                "lon": lons.tolist(),
                "u_velocity": u_vel.tolist(),
                "v_velocity": v_vel.tolist()
            },
            "constituents": _mesh.constituent_names
        }

        # Optional fields (skip to reduce payload)
        if include_depth:
            response["nodes"]["depth"] = _mesh.depth[node_indices].tolist()

        if include_elements:
            # Vectorized element filtering
            mask_0 = np.isin(_mesh.elements[:, 0], node_indices)
            mask_1 = np.isin(_mesh.elements[:, 1], node_indices)
            mask_2 = np.isin(_mesh.elements[:, 2], node_indices)
            valid_elements = _mesh.elements[mask_0 & mask_1 & mask_2]

            if len(valid_elements) > 0:
                # Remap to compact 0-based indices
                idx_map = np.empty(_mesh.lat.shape[0], dtype=np.int32)
                idx_map[node_indices] = np.arange(num_nodes, dtype=np.int32)
                elements_remapped = idx_map[valid_elements]
                response["elements"] = {
                    "count": len(elements_remapped),
                    "triangles": elements_remapped.tolist()
                }
            else:
                response["elements"] = {"count": 0, "triangles": []}

        elapsed = time_module.time() - start_time
        print(f"Mesh query: {num_nodes} nodes in {elapsed:.3f}s")

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/info")
async def get_dataset_info():
    """Get information about the dataset"""
    try:
        _load_mesh_data()

        return {
            "total_nodes": len(_mesh.lat),
            "total_elements": len(_mesh.elements),
            "constituents": _mesh.constituent_names,
            "tide_frequencies": _mesh.tidefreqs.tolist(),
            "lat_range": [float(_mesh.lat.min()), float(_mesh.lat.max())],
            "lon_range": [float(_mesh.lon.min()), float(_mesh.lon.max())],
            "depth_range": [float(_mesh.depth.min()), float(_mesh.depth.max())]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
