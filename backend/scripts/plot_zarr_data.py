#!/usr/bin/env python3
"""
Visualize Zarr tidal current data for verification.

This script plots the unstructured mesh and tidal current vectors
for a specific region to verify the data conversion is correct.

Usage:
    python plot_zarr_data.py
"""

import numpy as np
import xarray as xr
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from pathlib import Path
import sys


ZARR_STORE = Path(__file__).parent.parent.parent / "data" / "adcirc54.zarr"


def query_bounding_box(ds, min_lat, max_lat, min_lon, max_lon):
    """Query nodes within a bounding box."""
    lat_mask = (ds['lat'] >= min_lat) & (ds['lat'] <= max_lat)
    lon_mask = (ds['lon'] >= min_lon) & (ds['lon'] <= max_lon)
    bbox_mask = lat_mask & lon_mask
    return ds.where(bbox_mask, drop=True)


def plot_region(region_name, bbox, constituent_idx=0):
    """
    Plot tidal currents for a specific region.

    Args:
        region_name: Name of the region for the plot title
        bbox: Dictionary with min_lat, max_lat, min_lon, max_lon
        constituent_idx: Index of tidal constituent to plot (default=0 for M2)
    """
    print(f"\nPlotting {region_name}...")
    print(f"Bounding box: {bbox}")

    # Open Zarr store
    ds = xr.open_zarr(ZARR_STORE, consolidated=True)

    # Get constituent name
    constituent_name = str(ds['constituent_names'].isel(constituent=constituent_idx).values)
    print(f"Plotting constituent: {constituent_name}")

    # Query the region
    region_data = query_bounding_box(ds, **bbox)

    if region_data.sizes['node'] == 0:
        print(f"ERROR: No nodes found in bounding box!")
        return

    print(f"Nodes found: {region_data.sizes['node']:,}")

    # Extract coordinates and tidal data
    lats = region_data['lat'].values
    lons = region_data['lon'].values
    depths = region_data['depth'].values

    # Extract velocity components for the selected constituent
    u_amp = region_data['u_amp'].isel(constituent=constituent_idx).values
    v_amp = region_data['v_amp'].isel(constituent=constituent_idx).values
    u_phase = region_data['u_phase'].isel(constituent=constituent_idx).values
    v_phase = region_data['v_phase'].isel(constituent=constituent_idx).values

    # Calculate current speed (amplitude of velocity vector)
    speed = np.sqrt(u_amp**2 + v_amp**2)

    # Create figure with subplots
    fig, axes = plt.subplots(2, 2, figsize=(16, 14))
    fig.suptitle(f'{region_name} - {constituent_name} Tidal Currents',
                 fontsize=16, fontweight='bold')

    # ========== Plot 1: Node Locations (mesh density) ==========
    ax1 = axes[0, 0]
    scatter1 = ax1.scatter(lons, lats, c=depths, s=1, cmap='viridis_r', alpha=0.6)
    ax1.set_xlabel('Longitude (°E)', fontsize=11)
    ax1.set_ylabel('Latitude (°N)', fontsize=11)
    ax1.set_title(f'Mesh Nodes (n={len(lats):,})', fontsize=12, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.set_aspect('equal', adjustable='box')
    cbar1 = plt.colorbar(scatter1, ax=ax1)
    cbar1.set_label('Depth (m)', fontsize=10)

    # ========== Plot 2: Current Speed Amplitude ==========
    ax2 = axes[0, 1]
    scatter2 = ax2.scatter(lons, lats, c=speed, s=3, cmap='hot_r', alpha=0.7)
    ax2.set_xlabel('Longitude (°E)', fontsize=11)
    ax2.set_ylabel('Latitude (°N)', fontsize=11)
    ax2.set_title('Current Speed Amplitude (m/s)', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.set_aspect('equal', adjustable='box')
    cbar2 = plt.colorbar(scatter2, ax=ax2)
    cbar2.set_label('Speed (m/s)', fontsize=10)

    # ========== Plot 3: Current Vectors (quiver) ==========
    ax3 = axes[1, 0]

    # For quiver plot, subsample if too many points (for clarity)
    max_arrows = 2000
    if len(lats) > max_arrows:
        step = len(lats) // max_arrows
        idx = slice(0, len(lats), step)
        lons_sub = lons[idx]
        lats_sub = lats[idx]
        u_amp_sub = u_amp[idx]
        v_amp_sub = v_amp[idx]
        speed_sub = speed[idx]
    else:
        lons_sub = lons
        lats_sub = lats
        u_amp_sub = u_amp
        v_amp_sub = v_amp
        speed_sub = speed

    # Create quiver plot
    quiver = ax3.quiver(lons_sub, lats_sub, u_amp_sub, v_amp_sub,
                        speed_sub, cmap='plasma', alpha=0.8,
                        scale_units='xy', scale=0.5, width=0.002)
    ax3.set_xlabel('Longitude (°E)', fontsize=11)
    ax3.set_ylabel('Latitude (°N)', fontsize=11)
    ax3.set_title(f'Current Vectors ({len(lons_sub):,} arrows)',
                  fontsize=12, fontweight='bold')
    ax3.grid(True, alpha=0.3)
    ax3.set_aspect('equal', adjustable='box')
    cbar3 = plt.colorbar(quiver, ax=ax3)
    cbar3.set_label('Speed (m/s)', fontsize=10)

    # ========== Plot 4: Statistics Histogram ==========
    ax4 = axes[1, 1]
    ax4.hist(speed[speed > 0], bins=50, color='steelblue', alpha=0.7, edgecolor='black')
    ax4.set_xlabel('Current Speed (m/s)', fontsize=11)
    ax4.set_ylabel('Frequency', fontsize=11)
    ax4.set_title('Current Speed Distribution', fontsize=12, fontweight='bold')
    ax4.grid(True, alpha=0.3, axis='y')

    # Add statistics text
    stats_text = f"""Statistics:
    Nodes: {len(lats):,}
    Speed (m/s):
      Mean: {np.mean(speed):.3f}
      Median: {np.median(speed):.3f}
      Max: {np.max(speed):.3f}
      Min: {np.min(speed):.3f}
    Depth (m):
      Mean: {np.mean(depths):.1f}
      Max: {np.max(depths):.1f}
      Min: {np.min(depths):.1f}
    """
    ax4.text(0.98, 0.97, stats_text,
             transform=ax4.transAxes,
             verticalalignment='top',
             horizontalalignment='right',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5),
             fontsize=9,
             family='monospace')

    plt.tight_layout()

    # Save figure
    output_file = Path(__file__).parent.parent.parent / "data" / f"{region_name.replace(' ', '_').lower()}_plot.png"
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"Saved plot to: {output_file}")

    # Display
    plt.show()

    ds.close()


def main():
    """Main function to create visualizations."""

    if not ZARR_STORE.exists():
        print(f"ERROR: Zarr store not found: {ZARR_STORE}")
        print("Run convert_to_zarr.py first!")
        sys.exit(1)

    # Woods Hole, Massachusetts
    # Located at approximately 41.52°N, 70.67°W
    # This is a critical area with strong tidal currents through Vineyard Sound
    woods_hole_bbox = {
        'min_lat': 41.3,
        'max_lat': 41.7,
        'min_lon': -70.9,
        'max_lon': -70.5
    }

    plot_region("Woods Hole, MA", woods_hole_bbox, constituent_idx=0)

    print("\n" + "=" * 60)
    print("Visualization complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()
