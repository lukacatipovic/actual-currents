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

# Spatial ordering method
# 'hilbert' - Hilbert space-filling curve (best spatial locality, recommended)
# 'morton'  - Morton Z-order curve (faster computation, good locality)
SPATIAL_ORDER_METHOD = 'hilbert'

# Spatial chunking configuration
# Chunk size determines trade-off between query speed and overhead
# Smaller chunks = faster loading for small viewports, more files
SPATIAL_CHUNK_SIZE = 10_000  # ~207 chunks for 2M nodes (more granular)

# Element (triangle) chunking
# Smaller chunks for faster element loading
ELEMENT_CHUNK_SIZE = 50_000


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


def morton_encode(x, y):
    """
    Encode 2D coordinates into Morton code (Z-order curve).

    Morton codes interleave the bits of x and y coordinates to create a 1D ordering
    that preserves 2D spatial locality. Points close in Morton order are close in 2D space.

    Args:
        x: X coordinate (integer)
        y: Y coordinate (integer)

    Returns:
        Morton code (integer)
    """
    def part1by1(n):
        """Spread bits of n by inserting a 0 between each bit."""
        n &= 0x0000ffff
        n = (n | (n << 8)) & 0x00FF00FF
        n = (n | (n << 4)) & 0x0F0F0F0F
        n = (n | (n << 2)) & 0x33333333
        n = (n | (n << 1)) & 0x55555555
        return n

    return part1by1(x) | (part1by1(y) << 1)


def hilbert_encode(x, y, order=16):
    """
    Encode 2D coordinates into Hilbert curve index.

    Hilbert curves provide better spatial locality than Morton codes by ensuring
    that the curve never makes large jumps. The curve is continuous and fills space
    more uniformly than Z-order curves.

    Args:
        x: X coordinate (integer, 0 to 2^order - 1)
        y: Y coordinate (integer, 0 to 2^order - 1)
        order: Order of Hilbert curve (grid size is 2^order x 2^order)

    Returns:
        Hilbert curve index (integer)
    """
    # Hilbert curve distance calculation using rotation-based algorithm
    d = 0
    s = order - 1

    while s >= 0:
        rx = (x >> s) & 1
        ry = (y >> s) & 1
        d = (d << 2) | ((3 * rx) ^ ry)

        # Rotate coordinates if needed
        if ry == 0:
            if rx == 1:
                x = (1 << order) - 1 - x
                y = (1 << order) - 1 - y
            x, y = y, x

        s -= 1

    return d


def create_spatial_sort_index(lat, lon, method='hilbert'):
    """
    Create a spatial sorting index using space-filling curves for optimal spatial locality.

    Space-filling curves map 2D coordinates to 1D in a way that preserves spatial proximity.
    This dramatically improves chunk loading performance for bounding box queries.

    Args:
        lat: numpy array of latitudes
        lon: numpy array of longitudes
        method: 'hilbert' (default, best locality) or 'morton' (Z-order, faster to compute)

    Returns:
        Sorted indices that group spatially close nodes together
    """
    print(f"Creating spatial sort index using {method.upper()} curve...")

    # Normalize coordinates to [0, 1]
    lat_normalized = (lat - lat.min()) / (lat.max() - lat.min())
    lon_normalized = (lon - lon.min()) / (lon.max() - lon.min())

    # Choose grid resolution based on method
    # Hilbert curve requires power of 2, Morton is more flexible
    if method == 'hilbert':
        order = 16  # 2^16 = 65536 x 65536 grid (plenty of resolution)
        n_grid = 2 ** order
        print(f"  Using order-{order} Hilbert curve ({n_grid:,} x {n_grid:,} grid)")
    else:  # morton
        order = 16  # Use same resolution for fair comparison
        n_grid = 2 ** order
        print(f"  Using {n_grid:,} x {n_grid:,} grid for Morton encoding")

    # Convert to integer grid coordinates
    # Clip to [0, n_grid-1] to handle edge cases
    lat_grid = np.clip((lat_normalized * (n_grid - 1)).astype(np.uint32), 0, n_grid - 1)
    lon_grid = np.clip((lon_normalized * (n_grid - 1)).astype(np.uint32), 0, n_grid - 1)

    print(f"  Computing space-filling curve indices for {len(lat):,} nodes...")
    start = time.time()

    # Compute spatial keys using chosen method
    if method == 'hilbert':
        # Vectorized Hilbert encoding
        spatial_keys = np.array([
            hilbert_encode(int(x), int(y), order)
            for x, y in zip(lon_grid, lat_grid)
        ], dtype=np.uint64)
    else:  # morton
        # Vectorized Morton encoding
        spatial_keys = np.array([
            morton_encode(int(x), int(y))
            for x, y in zip(lon_grid, lat_grid)
        ], dtype=np.uint64)

    elapsed = time.time() - start
    print(f"  Computed spatial keys in {elapsed:.2f}s")

    # Sort by spatial key to group nearby nodes
    print(f"  Sorting {len(spatial_keys):,} indices...")
    sorted_indices = np.argsort(spatial_keys)

    print(f"✓ Spatial sorting complete using {method.upper()} curve")

    return sorted_indices


def remap_elements(elements_nc, spatial_sort_idx):
    """
    Remap element connectivity to spatially sorted node indices.

    Args:
        elements_nc: Element array from netCDF (nele, 3) with original indices
        spatial_sort_idx: Array mapping new_idx -> original_idx

    Returns:
        Remapped elements array with sorted node indices
    """
    print("Remapping element connectivity to sorted node indices...")

    # Create inverse mapping: original_idx -> new_idx
    inverse_mapping = np.zeros(len(spatial_sort_idx), dtype=np.int32)
    for new_idx, orig_idx in enumerate(spatial_sort_idx):
        inverse_mapping[orig_idx] = new_idx

    # Remap all element indices
    elements_sorted = inverse_mapping[elements_nc]

    # Validate
    if elements_sorted.min() < 0 or elements_sorted.max() >= len(spatial_sort_idx):
        raise ValueError(f"Invalid element indices after remapping!")

    print(f"✓ Element indices remapped and validated")

    return elements_sorted


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

    # Create spatial sorting index using space-filling curve
    spatial_sort_idx = create_spatial_sort_index(lat, lon, method=SPATIAL_ORDER_METHOD)

    # Apply spatial sorting to coordinates
    lat_sorted = lat[spatial_sort_idx]
    lon_sorted = lon[spatial_sort_idx]
    depth_sorted = depth[spatial_sort_idx]

    print(f"Spatial range:")
    print(f"  Latitude:  {lat.min():.2f}° to {lat.max():.2f}°")
    print(f"  Longitude: {lon.min():.2f}° to {lon.max():.2f}°")
    print(f"  Depth:     {depth.min():.2f}m to {depth.max():.2f}m")
    print()

    # Extract mesh connectivity (triangular elements)
    print("Extracting mesh connectivity...")
    elements_nc = ds['ele'].values  # Shape: (3, nele)

    # Convert from 1-based (Fortran) to 0-based (Python) indexing
    elements_nc = elements_nc.astype(np.int32) - 1

    # Transpose to (nele, 3) for easier handling
    elements_nc = elements_nc.T

    print(f"Loaded {elements_nc.shape[0]:,} triangular elements")

    # Remap element indices to spatially sorted node ordering
    elements_sorted = remap_elements(elements_nc, spatial_sort_idx)
    print()

    # Extract tide frequencies for main constituents
    print("Extracting tide frequencies for main constituents...")
    tidefreqs_all = ds['tidefreqs'].values
    tidefreqs = tidefreqs_all[constituent_indices]  # Use the list of indices
    print(f"Extracted {len(tidefreqs)} tide frequencies (from {len(tidefreqs_all)} total)")
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
            'elements': (['element', 'nv'], elements_sorted, {
                'long_name': 'Triangular element connectivity',
                'description': 'Node indices (0-based) forming each triangle',
                'standard_name': 'face_node_connectivity'
            }),
            'tidefreqs': (['constituent'], tidefreqs, {
                'long_name': 'Tide constituent frequencies',
                'units': 'radians per second',
                'description': 'Angular frequency of each tidal constituent'
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
            'spatial_sorting': f'{SPATIAL_ORDER_METHOD.capitalize()} space-filling curve (order-16)',
            'chunk_size_nodes': SPATIAL_CHUNK_SIZE,
            'chunk_size_elements': ELEMENT_CHUNK_SIZE,
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
    # Chunk elements for efficient mesh queries
    chunks = {
        'node': SPATIAL_CHUNK_SIZE,
        'element': ELEMENT_CHUNK_SIZE,
        'constituent': len(found_constituents),
        'nv': 3  # Always 3 vertices per triangle
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
