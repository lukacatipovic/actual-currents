#!/usr/bin/env python3
"""
Test Zarr spatial queries with bounding box.

This script demonstrates how to efficiently query the Zarr store for nodes
within a specific geographic bounding box.

Usage:
    python test_zarr_query.py
"""

import xarray as xr
import numpy as np
from pathlib import Path
import time


ZARR_STORE = Path(__file__).parent.parent.parent / "data" / "adcirc54.zarr"


def query_bounding_box(ds, min_lat, max_lat, min_lon, max_lon):
    """
    Query nodes within a bounding box.

    Args:
        ds: xarray Dataset opened from Zarr
        min_lat, max_lat: Latitude bounds
        min_lon, max_lon: Longitude bounds

    Returns:
        xarray Dataset with filtered nodes
    """
    # Create boolean mask for nodes in bounding box
    lat_mask = (ds['lat'] >= min_lat) & (ds['lat'] <= max_lat)
    lon_mask = (ds['lon'] >= min_lon) & (ds['lon'] <= max_lon)
    bbox_mask = lat_mask & lon_mask

    # Filter dataset
    ds_filtered = ds.where(bbox_mask, drop=True)

    return ds_filtered


def test_queries():
    """Run test queries on different regions."""

    print(f"Opening Zarr store: {ZARR_STORE}")
    print()

    # Open Zarr store
    ds = xr.open_zarr(ZARR_STORE, consolidated=True)

    print("Dataset info:")
    print(f"  Total nodes: {ds.dims['node']:,}")
    print(f"  Constituents: {', '.join([str(c.values) for c in ds['constituent_names']])}")
    print(f"  Latitude range: {float(ds['lat'].min()):.2f}° to {float(ds['lat'].max()):.2f}°")
    print(f"  Longitude range: {float(ds['lon'].min()):.2f}° to {float(ds['lon'].max()):.2f}°")
    print()

    # Test 1: Miami/Florida Keys area
    print("=" * 60)
    print("Test 1: Miami / Florida Keys")
    print("=" * 60)

    bbox = {
        'min_lat': 24.5,
        'max_lat': 26.0,
        'min_lon': -81.0,
        'max_lon': -80.0
    }

    start = time.time()
    result = query_bounding_box(ds, **bbox)
    query_time = time.time() - start

    print(f"Bounding box: {bbox}")
    print(f"Nodes found: {result.dims['node']:,}")
    print(f"Query time: {query_time*1000:.1f} ms")

    if result.dims['node'] > 0:
        # Get M2 constituent data (first constituent)
        m2_u_amp = result['u_amp'].isel(constituent=0).values
        m2_v_amp = result['v_amp'].isel(constituent=0).values

        # Calculate speed amplitude
        m2_speed = np.sqrt(m2_u_amp**2 + m2_v_amp**2)

        print(f"M2 constituent stats:")
        print(f"  Max speed amplitude: {np.nanmax(m2_speed):.3f} m/s")
        print(f"  Mean speed amplitude: {np.nanmean(m2_speed):.3f} m/s")
    print()

    # Test 2: Gulf of Mexico
    print("=" * 60)
    print("Test 2: Gulf of Mexico")
    print("=" * 60)

    bbox = {
        'min_lat': 25.0,
        'max_lat': 30.0,
        'min_lon': -95.0,
        'max_lon': -85.0
    }

    start = time.time()
    result = query_bounding_box(ds, **bbox)
    query_time = time.time() - start

    print(f"Bounding box: {bbox}")
    print(f"Nodes found: {result.dims['node']:,}")
    print(f"Query time: {query_time*1000:.1f} ms")

    if result.dims['node'] > 0:
        # Get M2 constituent data
        m2_u_amp = result['u_amp'].isel(constituent=0).values
        m2_v_amp = result['v_amp'].isel(constituent=0).values
        m2_speed = np.sqrt(m2_u_amp**2 + m2_v_amp**2)

        print(f"M2 constituent stats:")
        print(f"  Max speed amplitude: {np.nanmax(m2_speed):.3f} m/s")
        print(f"  Mean speed amplitude: {np.nanmean(m2_speed):.3f} m/s")
    print()

    # Test 3: New York Harbor
    print("=" * 60)
    print("Test 3: New York Harbor")
    print("=" * 60)

    bbox = {
        'min_lat': 40.0,
        'max_lat': 41.0,
        'min_lon': -74.5,
        'max_lon': -73.5
    }

    start = time.time()
    result = query_bounding_box(ds, **bbox)
    query_time = time.time() - start

    print(f"Bounding box: {bbox}")
    print(f"Nodes found: {result.dims['node']:,}")
    print(f"Query time: {query_time*1000:.1f} ms")

    if result.dims['node'] > 0:
        # Get M2 constituent data
        m2_u_amp = result['u_amp'].isel(constituent=0).values
        m2_v_amp = result['v_amp'].isel(constituent=0).values
        m2_speed = np.sqrt(m2_u_amp**2 + m2_v_amp**2)

        print(f"M2 constituent stats:")
        print(f"  Max speed amplitude: {np.nanmax(m2_speed):.3f} m/s")
        print(f"  Mean speed amplitude: {np.nanmean(m2_speed):.3f} m/s")

    print()
    print("=" * 60)
    print("All tests complete!")
    print("=" * 60)


def demonstrate_api_response():
    """
    Demonstrate how to format data for API response.
    This shows the structure you'll use in your FastAPI endpoint.
    """
    print()
    print("=" * 60)
    print("Example API Response Format")
    print("=" * 60)
    print()

    ds = xr.open_zarr(ZARR_STORE, consolidated=True)

    # Query a small area
    bbox = {
        'min_lat': 25.0,
        'max_lat': 25.5,
        'min_lon': -80.5,
        'max_lon': -80.0
    }

    result = query_bounding_box(ds, **bbox)

    if result.dims['node'] > 0:
        # Limit to first 10 nodes for demo
        sample = result.isel(node=slice(0, min(10, result.dims['node'])))

        # Format as you would for API response
        response_data = {
            'bbox': bbox,
            'node_count': int(result.dims['node']),
            'constituents': [str(result['constituent_names'].isel(constituent=i).values)
                           for i in range(len(result['constituent_names']))],
            'nodes': []
        }

        for i in range(sample.dims['node']):
            node_data = {
                'lat': float(sample['lat'].isel(node=i).values),
                'lon': float(sample['lon'].isel(node=i).values),
                'depth': float(sample['depth'].isel(node=i).values),
                'tidal_data': []
            }

            # Add constituent data
            for j, const_name in enumerate(response_data['constituents']):
                constituent_data = {
                    'constituent': const_name,
                    'u_amplitude': float(sample['u_amp'].isel(node=i, constituent=j).values),
                    'u_phase': float(sample['u_phase'].isel(node=i, constituent=j).values),
                    'v_amplitude': float(sample['v_amp'].isel(node=i, constituent=j).values),
                    'v_phase': float(sample['v_phase'].isel(node=i, constituent=j).values),
                }
                node_data['tidal_data'].append(constituent_data)

            response_data['nodes'].append(node_data)

        # Pretty print sample
        import json
        print("Sample API response (first node):")
        print(json.dumps({
            'bbox': response_data['bbox'],
            'node_count': response_data['node_count'],
            'constituents': response_data['constituents'],
            'sample_node': response_data['nodes'][0] if response_data['nodes'] else None
        }, indent=2))

    print()


if __name__ == '__main__':
    if not ZARR_STORE.exists():
        print(f"ERROR: Zarr store not found: {ZARR_STORE}")
        print("Run convert_to_zarr.py first!")
        import sys
        sys.exit(1)

    test_queries()
    demonstrate_api_response()
