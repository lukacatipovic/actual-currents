#!/usr/bin/env python3
"""
Benchmark different spatial ordering methods for Zarr chunking.

Compares:
- Simple grid-based ordering (row-major)
- Morton Z-order curve
- Hilbert space-filling curve

Measures spatial locality by computing average distance between consecutive nodes.
"""

import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import time
import sys

# Add parent directory to path to import conversion functions
sys.path.insert(0, str(Path(__file__).parent))
from convert_to_zarr import morton_encode, hilbert_encode


def simple_grid_ordering(lat, lon, n_grid=100):
    """Original simple grid-based approach."""
    lat_normalized = (lat - lat.min()) / (lat.max() - lat.min())
    lon_normalized = (lon - lon.min()) / (lon.max() - lon.min())

    lat_grid = (lat_normalized * n_grid).astype(int)
    lon_grid = (lon_normalized * n_grid).astype(int)

    spatial_key = lat_grid * (n_grid + 1) + lon_grid
    return np.argsort(spatial_key)


def morton_ordering(lat, lon, order=16):
    """Morton Z-order curve ordering."""
    lat_normalized = (lat - lat.min()) / (lat.max() - lat.min())
    lon_normalized = (lon - lon.min()) / (lon.max() - lon.min())

    n_grid = 2 ** order
    lat_grid = np.clip((lat_normalized * (n_grid - 1)).astype(np.uint32), 0, n_grid - 1)
    lon_grid = np.clip((lon_normalized * (n_grid - 1)).astype(np.uint32), 0, n_grid - 1)

    spatial_keys = np.array([
        morton_encode(int(x), int(y))
        for x, y in zip(lon_grid, lat_grid)
    ], dtype=np.uint64)

    return np.argsort(spatial_keys)


def hilbert_ordering(lat, lon, order=16):
    """Hilbert space-filling curve ordering."""
    lat_normalized = (lat - lat.min()) / (lat.max() - lat.min())
    lon_normalized = (lon - lon.min()) / (lon.max() - lon.min())

    n_grid = 2 ** order
    lat_grid = np.clip((lat_normalized * (n_grid - 1)).astype(np.uint32), 0, n_grid - 1)
    lon_grid = np.clip((lon_normalized * (n_grid - 1)).astype(np.uint32), 0, n_grid - 1)

    spatial_keys = np.array([
        hilbert_encode(int(x), int(y), order)
        for x, y in zip(lon_grid, lat_grid)
    ], dtype=np.uint64)

    return np.argsort(spatial_keys)


def compute_spatial_locality(lat, lon, sorted_indices):
    """
    Compute spatial locality metric: average distance between consecutive nodes.

    Lower is better - means nodes that are consecutive in the sorted order
    are also close in 2D space.
    """
    # Get sorted coordinates
    lat_sorted = lat[sorted_indices]
    lon_sorted = lon[sorted_indices]

    # Compute distances between consecutive nodes (in degrees)
    # Use simple Euclidean distance (good enough for comparison)
    dlat = np.diff(lat_sorted)
    dlon = np.diff(lon_sorted)
    distances = np.sqrt(dlat**2 + dlon**2)

    return {
        'mean_distance': np.mean(distances),
        'median_distance': np.median(distances),
        'p90_distance': np.percentile(distances, 90),
        'p99_distance': np.percentile(distances, 99),
        'max_distance': np.max(distances),
    }


def simulate_bbox_query_efficiency(lat, lon, sorted_indices, chunk_size=50000):
    """
    Simulate efficiency of bounding box queries by measuring how many chunks
    need to be loaded for typical query regions.

    Returns average chunk utilization (higher is better).
    """
    # Create several test bounding boxes
    lat_min, lat_max = lat.min(), lat.max()
    lon_min, lon_max = lon.min(), lon.max()

    # Generate 100 random bbox queries
    np.random.seed(42)
    n_queries = 100

    # Box size: 0.5 degrees (typical viewport)
    box_size = 0.5

    chunk_utilizations = []

    for _ in range(n_queries):
        # Random bbox
        bbox_lat_min = np.random.uniform(lat_min, lat_max - box_size)
        bbox_lat_max = bbox_lat_min + box_size
        bbox_lon_min = np.random.uniform(lon_min, lon_max - box_size)
        bbox_lon_max = bbox_lon_min + box_size

        # Find nodes in bbox
        in_bbox = (
            (lat >= bbox_lat_min) & (lat <= bbox_lat_max) &
            (lon >= bbox_lon_min) & (lon <= bbox_lon_max)
        )
        nodes_in_bbox = np.where(in_bbox)[0]

        if len(nodes_in_bbox) == 0:
            continue

        # Find where these nodes end up after sorting
        # Create reverse mapping: original_idx -> sorted_idx
        reverse_map = np.zeros(len(sorted_indices), dtype=int)
        for sorted_idx, orig_idx in enumerate(sorted_indices):
            reverse_map[orig_idx] = sorted_idx

        sorted_positions = reverse_map[nodes_in_bbox]

        # Compute which chunks would be loaded
        chunks_touched = np.unique(sorted_positions // chunk_size)
        total_nodes_in_chunks = len(chunks_touched) * chunk_size
        actual_nodes_needed = len(nodes_in_bbox)

        # Utilization: what % of loaded data is actually used?
        utilization = actual_nodes_needed / total_nodes_in_chunks if total_nodes_in_chunks > 0 else 0
        chunk_utilizations.append(utilization)

    return {
        'mean_utilization': np.mean(chunk_utilizations),
        'median_utilization': np.median(chunk_utilizations),
        'chunks_per_query_avg': np.mean([len(np.unique(reverse_map[nodes] // chunk_size))
                                          for nodes in [nodes_in_bbox]]),
    }


def visualize_ordering(lat, lon, sorted_indices, method_name, output_dir):
    """Create visualization of first 10,000 nodes in sorted order."""
    n_viz = 10000

    lat_sorted = lat[sorted_indices[:n_viz]]
    lon_sorted = lon[sorted_indices[:n_viz]]

    fig, ax = plt.subplots(1, 1, figsize=(12, 8))

    # Color by sorted index to show ordering
    scatter = ax.scatter(lon_sorted, lat_sorted, c=np.arange(n_viz),
                        s=1, cmap='viridis', alpha=0.6)

    # Draw line connecting consecutive points (subsample to avoid clutter)
    step = 50
    ax.plot(lon_sorted[::step], lat_sorted[::step], 'r-', alpha=0.3, linewidth=0.5)

    ax.set_xlabel('Longitude (°)')
    ax.set_ylabel('Latitude (°)')
    ax.set_title(f'{method_name} Ordering - First 10k Nodes\n(line shows traversal order)')

    plt.colorbar(scatter, ax=ax, label='Sort Index')
    plt.tight_layout()

    output_path = output_dir / f'ordering_{method_name.lower().replace(" ", "_")}.png'
    plt.savefig(output_path, dpi=150)
    plt.close()

    print(f"  Saved visualization to {output_path}")


def main():
    """Run benchmark comparing spatial ordering methods."""
    print("=" * 70)
    print("Spatial Ordering Benchmark")
    print("=" * 70)
    print()

    # Generate synthetic test data similar to ADCIRC mesh
    # (for real benchmark, load actual data from netCDF)
    print("Generating test data...")
    np.random.seed(42)

    # Create a dense coastal region and sparse offshore region
    # This mimics the ADCIRC mesh structure
    n_coastal = 50000  # Dense coastal nodes
    n_offshore = 30000  # Sparse offshore nodes

    # Coastal region: small area with high density
    lat_coastal = np.random.uniform(25.0, 26.0, n_coastal)
    lon_coastal = np.random.uniform(-80.5, -79.5, n_coastal)

    # Offshore region: large area with low density
    lat_offshore = np.random.uniform(20.0, 30.0, n_offshore)
    lon_offshore = np.random.uniform(-85.0, -75.0, n_offshore)

    # Combine
    lat = np.concatenate([lat_coastal, lat_offshore])
    lon = np.concatenate([lon_coastal, lon_offshore])

    print(f"Test mesh: {len(lat):,} nodes")
    print(f"  Coastal:  {n_coastal:,} nodes (dense)")
    print(f"  Offshore: {n_offshore:,} nodes (sparse)")
    print()

    # Create output directory for visualizations
    output_dir = Path(__file__).parent.parent.parent / "data" / "spatial_benchmark"
    output_dir.mkdir(exist_ok=True, parents=True)

    methods = {
        'Simple Grid': simple_grid_ordering,
        'Morton Z-Order': morton_ordering,
        'Hilbert Curve': hilbert_ordering,
    }

    results = {}

    for method_name, method_func in methods.items():
        print(f"Testing: {method_name}")
        print("-" * 70)

        # Compute ordering
        start = time.time()
        sorted_indices = method_func(lat, lon)
        elapsed = time.time() - start

        print(f"  Computation time: {elapsed:.2f}s")

        # Measure spatial locality
        locality = compute_spatial_locality(lat, lon, sorted_indices)
        print(f"  Spatial locality (consecutive node distance):")
        print(f"    Mean:   {locality['mean_distance']:.6f}°")
        print(f"    Median: {locality['median_distance']:.6f}°")
        print(f"    P90:    {locality['p90_distance']:.6f}°")
        print(f"    P99:    {locality['p99_distance']:.6f}°")

        # Simulate bbox query efficiency
        print(f"  Simulating 100 bbox queries...")
        query_efficiency = simulate_bbox_query_efficiency(lat, lon, sorted_indices)
        print(f"    Mean chunk utilization: {query_efficiency['mean_utilization']:.2%}")
        print(f"    (higher is better - less wasted data loading)")

        # Visualize ordering
        print(f"  Creating visualization...")
        visualize_ordering(lat, lon, sorted_indices, method_name, output_dir)

        results[method_name] = {
            'computation_time': elapsed,
            'locality': locality,
            'query_efficiency': query_efficiency,
        }

        print()

    # Summary comparison
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print(f"{'Method':<20} {'Mean Dist (°)':<15} {'Chunk Util':<15} {'Comp Time':<12}")
    print("-" * 70)

    for method_name, result in results.items():
        mean_dist = result['locality']['mean_distance']
        utilization = result['query_efficiency']['mean_utilization']
        comp_time = result['computation_time']

        print(f"{method_name:<20} {mean_dist:<15.6f} {utilization:<15.2%} {comp_time:<12.2f}s")

    print()
    print("Interpretation:")
    print("  - Lower mean distance = better spatial locality")
    print("  - Higher chunk utilization = fewer wasted chunk reads")
    print()
    print(f"Visualizations saved to: {output_dir}")
    print("=" * 70)


if __name__ == '__main__':
    main()
