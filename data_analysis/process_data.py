import argparse
import logging
from pathlib import Path
import pandas as pd
from tqdm import tqdm
import data_analysis as da

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DataProcessor")

def main():
    parser = argparse.ArgumentParser(description="Process Kinetic Spectroscopy Data")
    parser.add_argument("--data_dir", type=str, required=True, help="Path to the date-specific data folder (e.g., C:/data/2025-12-01)")
    args = parser.parse_args()

    data_directory = Path(args.data_dir)
    if not data_directory.exists():
        logger.error(f"Directory not found: {data_directory}")
        return

    # 1. Identify Reaction Folders
    # Assumes folders start with digit (e.g., "01_Reaction...")
    reaction_folders = [f.name for f in data_directory.iterdir() if f.is_dir() and f.name[0].isdigit()]
    logger.info(f"Found {len(reaction_folders)} reaction folders.")

    # 2. Load Parameters
    try:
        param_file = list(data_directory.glob('reaction_parameters*.csv'))[0]
        reaction_params_df = pd.read_csv(param_file)
    except IndexError:
        logger.error("CRITICAL: 'reaction_parameters.csv' not found.")
        return

    # 3. Processing Loop
    logger.info("Starting individual reaction processing...")
    
    for folder in tqdm(reaction_folders, desc="Processing"):
        # A. Clean & Standardize
        da.standardize_time_axis(data_directory, folder, reaction_params_df)
        
        # B. Smooth & Merge
        da.apply_smoothing(data_directory, folder)
        da.merge_vis_nir_spectra(data_directory, folder)
        
        # C. Visualize
        da.plot_reaction_heatmap(data_directory, folder)
        
        # D. Feature Extraction (FWHM, Peak Position)
        da.extract_spectral_features(data_directory, folder)

    # 4. Global Compilation
    logger.info("Compiling global summary traces...")
    da.compile_experiment_traces(data_directory, reaction_folders)
    
    logger.info("✅ Workflow finished successfully.")

if __name__ == "__main__":
    main()