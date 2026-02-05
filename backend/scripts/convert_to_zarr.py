#!/usr/bin/env python3
"""
Convert ADCIRC netCDF tidal constituent data to Zarr format with spatial chunking.

This script converts the 2M+ node irregular mesh data to Zarr with optimized
chunking for fast spatial (bounding box) queries.

Usage:
    python convert_to_zarr.py
"""

import numpy as np
import xarray as xr
import zarr
from numcodecs import Blosc
from pathlib import Path
import sys
import time


# Configuration
NC_FILE = Path(__file__).parent.parent.parent / "data" / "adcirc54.nc"
ZARR_OUTPUT = Path(__file__).parent.parent.parent / "data" / "adcirc54.zarr"

# Main tidal constituents to extract (can adjust this list)
MAIN_CONSTITUENTS = ['M2', 'S2', 'N2', 'K1', 'O1', 'P1', 'M4', 'M6']

# Spatial chunking configuration
# Chunk size determines trade-off between query speed and overhead
# ~50k nodes per chunk is a good balance for 2M total nodes
SPATIAL_CHUNK_SIZE = 50_000


def parse_tide_names(tidenames_array):
    """
    Parse tide names from bytes array to list of strings.

    Args:
        tidenames_array: numpy array with dtype |S10 (bytes strings)

    Returns:
        List of tide constituent names
    """
    names = []
    for tide in tidenames_array:
        # Decode bytes to string and strip whitespace
        if isinstance(tide, bytes):
            name = tide.decode('utf-8').strip()
        else:
            # Handle case where it's already a string
            name = str(tide).strip()
        names.append(name)
    return names


def create_spatial_sort_index(lat, lon):
    """
    Create a spatial sorting index using a simple grid-based approach.
    This groups nearby nodes together for better spatial locality.

    Args:
        lat: numpy array of latitudes
        lon: numpy array of longitudes

    Returns:
        Sorted indices that group spatially close nodes
    """
    print("Creating spatial sort index...")

    # Create a simple grid-based hash for spatial sorting
    # Divide the space into ~100x100 grid cells
    lat_normalized = (lat - lat.min()) / (lat.max() - lat.min())
    lon_normalized = (lon - lon.min()) / (lon.max() - lon.min())

    # Create grid cell indices
    n_grid = 100
    lat_grid = (lat_normalized * n_grid).astype(int)
    lon_grid = (lon_normalized * n_grid).astype(int)

    # Create a combined spatial key for sorting
    spatial_key = lat_grid * (n_grid + 1) + lon_grid

    # Sort by spatial key to group nearby nodes
    sorted_indices = np.argsort(spatial_key)

    return sorted_indices


def convert_to_zarr():
    """
    Main conversion function: netCDF -> Zarr with spatial chunking.
    """
    print(f"Reading netCDF file: {NC_FILE}")
    print(f"Output Zarr store: {ZARR_OUTPUT}")
    print()

    start_time = time.time()

    # Open the netCDF file with xarray
    ds = xr.open_dataset(NC_FILE)

    print(f"Dataset dimensions: {dict(ds.sizes)}")
    print(f"Total nodes: {ds.sizes['node']:,}")
    print()

    # Parse tide constituent names
    tidenames = parse_tide_names(ds['tidenames'].values)
    print(f"Found {len(tidenames)} tidal constituents:")
    print(f"  {', '.join(tidenames)}")
    print()

    # Find indices for main constituents
    constituent_indices = []
    found_constituents = []
    for const in MAIN_CONSTITUENTS:
        try:
            idx = tidenames.index(const)
            constituent_indices.append(idx)
            found_constituents.append(const)
        except ValueError:
            print(f"Warning: Constituent '{const}' not found in dataset")

    print(f"Extracting {len(found_constituents)} main constituents:")
    print(f"  {', '.join(found_constituents)}")
    print()

    # Extract coordinate data
    lat = ds['lat'].values
    lon = ds['lon'].values
    depth = ds['depth'].values

    # Create spatial sorting index
    spatial_sort_idx = create_spatial_sort_index(lat, lon)

    # Apply spatial sorting to coordinates
    lat_sorted = lat[spatial_sort_idx]
    lon_sorted = lon[spatial_sort_idx]
    depth_sorted = depth[spatial_sort_idx]

    print(f"Spatial range:")
    print(f"  Latitude:  {lat.min():.2f}° to {lat.max():.2f}°")
    print(f"  Longitude: {lon.min():.2f}° to {lon.max():.2f}°")
    print(f"  Depth:     {depth.min():.2f}m to {depth.max():.2f}m")
    print()

    # Extract and sort amplitude and phase data for main constituents
    # Note: u_amp and v_amp have shape (depth-averaged, node, ntides)
    # We want to extract specific constituents and sort by spatial index

    print("Extracting velocity components...")

    # Remove the depth-averaged dimension first (get all constituents)
    u_amp_all = ds['u_amp'].values[0, :, :]  # Shape: (node, ntides)
    v_amp_all = ds['v_amp'].values[0, :, :]
    u_phase_all = ds['u_phase'].values[0, :, :]
    v_phase_all = ds['v_phase'].values[0, :, :]

    # Apply spatial sorting first (to all constituents)
    u_amp_sorted_all = u_amp_all[spatial_sort_idx, :]
    v_amp_sorted_all = v_amp_all[spatial_sort_idx, :]
    u_phase_sorted_all = u_phase_all[spatial_sort_idx, :]
    v_phase_sorted_all = v_phase_all[spatial_sort_idx, :]

    # Now select only the main constituents using numpy array indexing
    constituent_indices_arr = np.array(constituent_indices)
    u_amp_sorted = u_amp_sorted_all[:, constituent_indices_arr]
    v_amp_sorted = v_amp_sorted_all[:, constituent_indices_arr]
    u_phase_sorted = u_phase_sorted_all[:, constituent_indices_arr]
    v_phase_sorted = v_phase_sorted_all[:, constituent_indices_arr]

    # Create new xarray dataset with sorted data and proper chunking
    print(f"Creating Zarr dataset with spatial chunks of {SPATIAL_CHUNK_SIZE:,} nodes...")

    ds_zarr = xr.Dataset(
        {
            'lat': (['node'], lat_sorted, {
                'long_name': 'Latitude',
                'units': 'degrees_north',
                'standard_name': 'latitude'
            }),
            'lon': (['node'], lon_sorted, {
                'long_name': 'Longitude',
                'units': 'degrees_east',
                'standard_name': 'longitude'
            }),
            'depth': (['node'], depth_sorted, {
                'long_name': 'Bathymetric depth',
                'units': 'meters',
                'positive': 'down'
            }),
            'u_amp': (['node', 'constituent'], u_amp_sorted, {
                'long_name': 'Eastward velocity amplitude',
                'units': 'm/s',
                'description': 'Amplitude of eastward (u) velocity component'
            }),
            'v_amp': (['node', 'constituent'], v_amp_sorted, {
                'long_name': 'Northward velocity amplitude',
                'units': 'm/s',
                'description': 'Amplitude of northward (v) velocity component'
            }),
            'u_phase': (['node', 'constituent'], u_phase_sorted, {
                'long_name': 'Eastward velocity phase',
                'units': 'degrees',
                'description': 'Phase of eastward (u) velocity component'
            }),
            'v_phase': (['node', 'constituent'], v_phase_sorted, {
                'long_name': 'Northward velocity phase',
                'units': 'degrees',
                'description': 'Phase of northward (v) velocity component'
            }),
            'constituent_names': (['constituent'], found_constituents, {
                'long_name': 'Tidal constituent names'
            }),
        },
        attrs={
            'title': 'ADCIRC Tidal Constituents (Zarr format)',
            'source': str(NC_FILE),
            'model': 'ADCIRC',
            'grid_type': 'Irregular triangular mesh',
            'institution': 'NOAA/NOS/OCS/CSDL/MMAP',
            'spatial_sorting': 'Grid-based spatial locality',
            'chunk_size': SPATIAL_CHUNK_SIZE,
            'created': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
    )

    # Add the original node indices as a variable (for reference)
    ds_zarr['original_node_index'] = (['node'], spatial_sort_idx, {
        'long_name': 'Original node index in source netCDF',
        'description': 'Maps sorted nodes back to original netCDF indices'
    })

    # Define chunking strategy
    # Chunk along the node dimension for spatial queries
    # Keep all constituents together since they're usually queried together
    chunks = {
        'node': SPATIAL_CHUNK_SIZE,
        'constituent': len(found_constituents)
    }

    # Write to Zarr format
    print(f"Writing Zarr store to {ZARR_OUTPUT}...")

    # Remove existing zarr store if it exists
    if ZARR_OUTPUT.exists():
        import shutil
        shutil.rmtree(ZARR_OUTPUT)

    # Write to Zarr with default compression (automatically uses efficient codecs)
    # Zarr v3 uses good defaults, so we don't need to specify encoding
    ds_zarr.to_zarr(
        ZARR_OUTPUT,
        mode='w',
        consolidated=True,  # Create consolidated metadata for faster access
        compute=True
    )

    elapsed = time.time() - start_time

    print()
    print("=" * 60)
    print("Conversion complete!")
    print(f"Time elapsed: {elapsed:.1f} seconds")
    print(f"Output size: {get_dir_size(ZARR_OUTPUT) / 1e9:.2f} GB")
    print(f"Zarr store: {ZARR_OUTPUT}")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Test spatial queries with scripts/test_zarr_query.py")
    print("  2. Build API endpoint for bounding box queries")
    print("=" * 60)

    ds.close()


def get_dir_size(path):
    """Calculate total size of a directory."""
    total = 0
    for entry in Path(path).rglob('*'):
        if entry.is_file():
            total += entry.stat().st_size
    return total


if __name__ == '__main__':
    if not NC_FILE.exists():
        print(f"ERROR: Input file not found: {NC_FILE}")
        sys.exit(1)

    print("=" * 60)
    print("ADCIRC netCDF to Zarr Converter")
    print("=" * 60)
    print()

    convert_to_zarr()
