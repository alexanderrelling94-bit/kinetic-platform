import logging
import pandas as pd
import numpy as np
from scipy.signal import savgol_filter
from scipy.interpolate import interp1d
from pathlib import Path
from typing import List, Union, Optional
import matplotlib.pyplot as plt

# Configure Logger
logger = logging.getLogger(__name__)

# --- Physical Constants ---
HC_CONST = 1239.84193  # Planck * Speed of Light (eV * nm)

# --- File Conventions ---
NIR_PREFIX = 'Emission_nir'
VIS_PREFIX = 'Emission_vis'


def _get_file_by_prefix(directory: Path, prefix: str) -> Path:
    """Helper to find a specific file in a directory safely."""
    files = list(directory.glob(f"{prefix}*.csv"))
    if not files:
        raise FileNotFoundError(f"No file found starting with '{prefix}' in {directory}")
    return files[0]

def standardize_time_axis(
    directory: Union[str, Path], 
    folder: str, 
    reaction_params_df: pd.DataFrame
) -> None:
    """
    Aligns raw spectral data columns to the theoretical time points.
    Filters out wavelengths < 500nm (VIS) to remove excitation saturation.
    """
    base_path = Path(directory) / folder
    raw_path = base_path / 'corrected_data'
    output_path = base_path / 'cleaned_data'
    output_path.mkdir(parents=True, exist_ok=True)

    # Parse Reaction ID from folder name (e.g. "01_Ratio-10...")
    try:
        reaction_id = int(folder.split('_')[0])
        params = reaction_params_df[reaction_params_df['reaction_id'] == reaction_id].iloc[0]
    except (IndexError, ValueError):
        logger.warning(f"Skipping {folder}: Could not parse reaction number from folder name.")
        return

    # Create theoretical time axis
    time_points = np.arange(0, params['num_measurements'], params['frequency'], dtype=int)

    for sensor, prefix in [('nir', NIR_PREFIX), ('vis', VIS_PREFIX)]:
        try:
            file_path = _get_file_by_prefix(raw_path, f"{prefix}_corrected")
            df = pd.read_csv(file_path, index_col=0)

            # Ensure numeric index (Wavelengths)
            df.index = pd.to_numeric(df.index, errors='coerce')
            
            # Wavelength Cutoff (VIS only)
            if prefix == VIS_PREFIX: 
                df = df[df.index >= 500]

            # Validation: Match data shape to time points
            if df.shape[1] != len(time_points):
                # Trim to shorter length if mismatch occurs (e.g. manual stop)
                min_len = min(df.shape[1], len(time_points))
                df = df.iloc[:, :min_len]
                current_time_points = time_points[:min_len]
            else:
                current_time_points = time_points

            # Assign calibrated time headers
            df.columns = current_time_points
            df.to_csv(output_path / f"{prefix}_cleaned.csv")
            
        except FileNotFoundError:
            logger.warning(f"File missing for {folder}/{prefix}")
        except Exception as e:
            logger.error(f"Error standardizing {folder}/{prefix}: {e}")

def apply_smoothing(
    directory: Union[str, Path], 
    folder: str, 
    window_length: int = 11, 
    polyorder: int = 2
) -> None:
    """
    Applies a Savitzky-Golay filter to smooth spectral data along the wavelength axis.
    """
    base_path = Path(directory) / folder
    input_path = base_path / 'cleaned_data'
    output_path = base_path / 'smoothed_data'
    output_path.mkdir(parents=True, exist_ok=True)

    for prefix in [NIR_PREFIX, VIS_PREFIX]:
        try:
            input_file = input_path / f"{prefix}_cleaned.csv"
            if not input_file.exists():
                continue
            
            df = pd.read_csv(input_file, index_col=0)
            df.index = df.index.astype(float).round(1)
            
            # Apply Filter (Axis 0 = Wavelength)
            smoothed_data = savgol_filter(df, window_length=window_length, polyorder=polyorder, axis=0)
            
            df_smoothed = pd.DataFrame(smoothed_data, columns=df.columns, index=df.index).round(2)
            df_smoothed.to_csv(output_path / f"{prefix}_smoothed.csv")

        except Exception as e:
            logger.error(f"Error smoothing {folder}/{prefix}: {e}")

def merge_vis_nir_spectra(
    directory: Union[str, Path], 
    folder: str, 
    stitch_wavelength: float = 930.0, 
    stitch_window: float = 10.0,
    min_signal_threshold: float = 50.0
) -> None:
    """
    Merges VIS and NIR spectra, scaling VIS to match NIR at the stitch point.
    """
    base_path = Path(directory) / folder
    input_path = base_path / 'smoothed_data'
    output_path = base_path / 'merged_data'
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        path_nir = input_path / f"{NIR_PREFIX}_smoothed.csv"
        path_vis = input_path / f"{VIS_PREFIX}_smoothed.csv"

        if not path_nir.exists() and not path_vis.exists():
            return
            
        # Handle single-file cases
        if not path_vis.exists():
            pd.read_csv(path_nir, index_col=0).to_csv(output_path / 'Emission_merged.csv')
            return
        if not path_nir.exists():
            pd.read_csv(path_vis, index_col=0).to_csv(output_path / 'Emission_merged.csv')
            return

        # Load
        df_nir = pd.read_csv(path_nir, index_col=0)
        df_vis = pd.read_csv(path_vis, index_col=0)
        df_nir.index = df_nir.index.astype(float)
        df_vis.index = df_vis.index.astype(float)
        
        # Align Columns
        common_cols = df_nir.columns.intersection(df_vis.columns)
        df_nir = df_nir[common_cols]
        df_vis = df_vis[common_cols]

        # Calculate Scaling
        nir_region = df_nir.loc[(df_nir.index >= stitch_wavelength - stitch_window) & 
                                (df_nir.index <= stitch_wavelength + stitch_window)]
        vis_region = df_vis.loc[(df_vis.index >= stitch_wavelength - stitch_window) & 
                                (df_vis.index <= stitch_wavelength + stitch_window)]

        vis_means = vis_region.mean(axis=0)
        nir_means = nir_region.mean(axis=0)
        
        # Only scale if signal is significant
        scaling_factors = np.where(
            vis_means > min_signal_threshold,
            nir_means / vis_means,
            1.0
        )
        scaling_factors = pd.Series(scaling_factors, index=vis_means.index).fillna(1.0).replace([np.inf, -np.inf], 1.0)

        df_vis_scaled = df_vis.multiply(scaling_factors, axis=1)

        # Stitch
        part_vis = df_vis_scaled.loc[df_vis_scaled.index < stitch_wavelength]
        part_nir = df_nir.loc[df_nir.index >= stitch_wavelength]

        df_merged = pd.concat([part_vis, part_nir]).sort_index()
        df_merged.to_csv(output_path / 'Emission_merged.csv')
        
    except Exception as e:
        logger.error(f"Error merging {folder}: {e}")

def plot_reaction_heatmap(directory: Union[str, Path], folder: str) -> None:
    """Generates 2D Spectral Heatmaps."""
    root_path = Path(directory)
    plot_configs = [
        ('smoothed_data', f"{VIS_PREFIX}_smoothed.csv", 'VIS'),
        ('smoothed_data', f"{NIR_PREFIX}_smoothed.csv", 'NIR'),
        ('merged_data', 'Emission_merged.csv', 'Merged')
    ]

    for subfolder, filename, label in plot_configs:
        file_path = root_path / folder / subfolder / filename
        if not file_path.exists(): continue
            
        try:
            df = pd.read_csv(file_path, index_col=0)
            wavelengths = df.index.astype(float)
            times = df.columns.astype(float)
            intensity = df.values.T 
            
            fig, ax = plt.subplots(figsize=(8, 10))
            c = ax.pcolormesh(wavelengths, times, intensity, shading='auto', cmap='inferno')
            plt.colorbar(c, ax=ax, label='Intensity')
            
            ax.set_title(f"{folder} ({label})")
            ax.set_xlabel('Wavelength (nm)')
            ax.set_ylabel('Time (s)')
            
            save_dir = root_path / folder / 'plots'
            save_dir.mkdir(exist_ok=True)
            plt.savefig(save_dir / f"Heatmap_{label}.png", dpi=150)
            plt.close(fig)

        except Exception as e:
            logger.error(f"Error plotting {folder}/{label}: {e}")

def extract_spectral_features(
    directory: Union[str, Path], 
    folder: str, 
    intensity_threshold: float = 50.0,
    time_threshold: float = 100.0
) -> None:
    """
    Extracts Peak Intensity, Position (nm), and FWHM (eV).
    Includes Jacobian transformation for correct energy-space FWHM.
    """
    base_path = Path(directory) / folder
    input_file = base_path / 'smoothed_data' / 'Emission_nir_smoothed.csv'
    
    if not input_file.exists():
        return

    df = pd.read_csv(input_file, index_col=0)
    wavelengths = df.index.astype(float).values
    energies = HC_CONST / wavelengths # E = hc / lambda

    results = []
    for timestamp in df.columns:
        intensity = df[timestamp].values
        
        peak_idx = np.argmax(intensity)
        peak_int = intensity[peak_idx]
        peak_wl = wavelengths[peak_idx]
        
        # Noise Filter
        if peak_int < intensity_threshold and float(timestamp) > time_threshold:
            results.append({'timestamp': timestamp, 'max_intensity': peak_int, 'peak_wavelength': np.nan, 'fwhm_ev': np.nan})
            continue

        # Jacobian transformation: I(E) = I(lambda) * (lambda^2 / hc)
        jacobian_factor = HC_CONST / (energies ** 2)
        intensity_ev = intensity * jacobian_factor
        
        # FWHM Calculation in Energy Space
        peak_idx_ev = np.argmax(intensity_ev)
        half_max = intensity_ev[peak_idx_ev] / 2.0
        
        try:
            # Interpolated crossing points
            left_mask = np.arange(len(intensity_ev)) < peak_idx_ev
            left_idx = np.where(left_mask & (intensity_ev < half_max))[0][-1]
            
            right_mask = np.arange(len(intensity_ev)) > peak_idx_ev
            right_idx = np.where(right_mask & (intensity_ev < half_max))[0][0]
            
            # Linear Interpolation
            f_left = interp1d(intensity_ev[left_idx:left_idx+2], energies[left_idx:left_idx+2])
            e_left = f_left(half_max)
            
            f_right = interp1d(intensity_ev[right_idx-1:right_idx+1], energies[right_idx-1:right_idx+1])
            e_right = f_right(half_max)
            
            fwhm = abs(float(e_left - e_right))
        except (IndexError, ValueError):
            fwhm = np.nan

        results.append({
            'timestamp': timestamp,
            'max_intensity': peak_int,
            'peak_wavelength': peak_wl,
            'fwhm_ev': fwhm
        })

    pd.DataFrame(results).to_csv(base_path / 'Emission_features_nir.csv', index=False)

def compile_experiment_traces(
    directory: Union[str, Path], 
    folders: List[str], 
    window_length: int = 11, 
    polyorder: int = 2
) -> None:
    """Aggregates features from all reactions into summary files."""
    root_path = Path(directory)
    collector = {'max_intensity': [], 'peak_wavelength': [], 'fwhm_ev': []}
    
    for folder in folders:
        feature_file = root_path / folder / 'Emission_features_nir.csv'
        if not feature_file.exists(): continue
            
        df = pd.read_csv(feature_file)
        df.set_index('timestamp', inplace=True)
        
        for metric in collector.keys():
            # Smooth kinetic traces to remove outliers
            smoothed = savgol_filter(df[metric].interpolate().bfill().ffill(), window_length, polyorder)
            s = pd.Series(smoothed, index=df.index, name=folder)
            collector[metric].append(s)

    # Save compiled files
    for metric, series_list in collector.items():
        if series_list:
            pd.concat(series_list, axis=1).to_csv(root_path / f'summary_{metric}_nir.csv')