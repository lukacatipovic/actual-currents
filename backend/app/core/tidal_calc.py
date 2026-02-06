"""
Tidal current prediction using harmonic constituent synthesis

Implements the ADCIRC tidal harmonic prediction algorithm with nodal corrections.
"""

from datetime import datetime, timezone
import numpy as np
from matplotlib.dates import date2num
from ttide.t_vuf import t_vuf


# ADCIRC reference time: 2000-01-01 00:00:00 UTC
REFERENCE_TIME = datetime(2000, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


# Standard ADCIRC constituent mapping to ttide indices
# These are the standard 8 tidal constituents used in ADCIRC
_STANDARD_CONST_INDICES = {
    'M2': 0,   # Principal lunar semidiurnal
    'S2': 1,   # Principal solar semidiurnal
    'N2': 2,   # Larger lunar elliptic semidiurnal
    'K1': 3,   # Lunisolar diurnal
    'O1': 4,   # Lunar diurnal
    'P1': 5,   # Solar diurnal
    'M4': 6,   # Shallow water overtide
    'M6': 7,   # Shallow water overtide
}


def _get_ttide_indices(constituent_names):
    """
    Get ttide constituent indices for given names

    For standard ADCIRC constituents, use hardcoded mapping.
    This avoids issues with ttide's constituent table format.
    """
    indices = []
    for name in constituent_names:
        if name in _STANDARD_CONST_INDICES:
            indices.append(_STANDARD_CONST_INDICES[name])
        else:
            # Fallback: use sequential index
            print(f"Warning: Constituent {name} not in standard mapping, using sequential index")
            indices.append(len(indices))

    return np.array(indices)


def predict_currents(
    u_amp: np.ndarray,      # Shape: (n_nodes, n_constituents)
    v_amp: np.ndarray,      # Shape: (n_nodes, n_constituents)
    u_phase: np.ndarray,    # Shape: (n_nodes, n_constituents) - degrees
    v_phase: np.ndarray,    # Shape: (n_nodes, n_constituents) - degrees
    tidefreqs: np.ndarray,  # Shape: (n_constituents,) - rad/s
    constituent_names: list,  # List of constituent names (e.g., ['M2', 'S2', ...])
    time_utc: datetime,
    lat: float = 55.0
) -> tuple[np.ndarray, np.ndarray]:
    """
    Predict instantaneous tidal current velocities using harmonic synthesis

    Implements the algorithm:
        U = Σ [ f[i] * u_amp[i] * cos(v[i] + ω[i]*t + u[i] - u_phase[i]) ]
        V = Σ [ f[i] * v_amp[i] * cos(v[i] + ω[i]*t + u[i] - v_phase[i]) ]

    where:
        v = equilibrium argument (astronomic phase offset)
        u = Greenwich phase lag
        f = nodal amplitude correction factor
        ω = angular frequency (rad/s)
        t = time in seconds since reference epoch

    Args:
        u_amp: Eastward velocity amplitudes (m/s)
        v_amp: Northward velocity amplitudes (m/s)
        u_phase: Eastward velocity phases (degrees)
        v_phase: Northward velocity phases (degrees)
        tidefreqs: Angular frequencies for each constituent (rad/s)
        constituent_names: Names of tidal constituents (e.g., ['M2', 'S2', 'N2', ...])
        time_utc: Prediction time
        lat: Latitude for nodal corrections (default: 55.0°N)

    Returns:
        (u_velocity, v_velocity) - Instantaneous velocities in m/s
            Shape: (n_nodes,) for each
    """
    # Ensure datetime is timezone-aware
    if time_utc.tzinfo is None:
        time_utc = time_utc.replace(tzinfo=timezone.utc)

    # Convert to matplotlib date format (days since 0001-01-01 UTC + 366)
    # This is the format expected by ttide
    mpl_date = date2num(time_utc) + 366

    # Get ttide constituent indices
    ttide_indices = _get_ttide_indices(constituent_names)

    # Get nodal corrections from ttide
    # v, u are in "cycles" (not degrees or radians), f is dimensionless
    # Returns arrays of shape (n_constituents,)
    v_node, u_node, f_node = t_vuf('nodal', mpl_date, ju=ttide_indices, lat=lat)

    # Squeeze any extra dimensions
    v_node = np.squeeze(v_node)
    u_node = np.squeeze(u_node)
    f_node = np.squeeze(f_node)

    # Convert v and u from cycles to radians
    # (ttide returns cycles, need to multiply by 2π)
    v_rad = v_node * 2 * np.pi  # Shape: (n_constituents,)
    u_rad = u_node * 2 * np.pi  # Shape: (n_constituents,)

    # Calculate seconds since ADCIRC reference time
    time_delta = time_utc - REFERENCE_TIME
    t_seconds = time_delta.total_seconds()

    # Calculate omega * t for all constituents
    # tidefreqs is in rad/s, t_seconds is in seconds
    omega_t = tidefreqs * t_seconds  # Shape: (n_constituents,)

    # Convert phase data from degrees to radians
    u_phase_rad = np.deg2rad(u_phase)  # Shape: (n_nodes, n_constituents)
    v_phase_rad = np.deg2rad(v_phase)  # Shape: (n_nodes, n_constituents)

    # Initialize velocity arrays
    n_nodes = u_amp.shape[0]
    u_velocity = np.zeros(n_nodes)
    v_velocity = np.zeros(n_nodes)

    # Harmonic synthesis - sum contributions from all constituents
    # Loop over constituents to properly handle broadcasting
    for i in range(len(constituent_names)):
        # Calculate phase angles for this constituent
        phase_u = v_rad[i] + omega_t[i] + u_rad[i] - u_phase_rad[:, i]
        phase_v = v_rad[i] + omega_t[i] + u_rad[i] - v_phase_rad[:, i]

        # Add contribution from this constituent
        u_velocity += f_node[i] * u_amp[:, i] * np.cos(phase_u)
        v_velocity += f_node[i] * v_amp[:, i] * np.cos(phase_v)

    return u_velocity, v_velocity
