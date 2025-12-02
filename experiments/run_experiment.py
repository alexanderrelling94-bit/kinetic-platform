import os
import sys
import time
import logging
import shutil
from pathlib import Path
from datetime import datetime
from collections import deque
import pandas as pd
import numpy as np

# --- 1. Project Setup ---
# Add parent directory to path to find drivers
CURRENT_DIR = Path(__file__).parent.absolute()
PARENT_DIR = CURRENT_DIR.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.append(str(PARENT_DIR))

# Import Drivers
from Hardware_Drivers.PressureController_OB import PressureController
from Hardware_Drivers.ValveController_MuxWire import MuxWire
from Hardware_Drivers.MultiValve_MuxDistribution import MuxDistribution
from Hardware_Drivers.StirrerController import StirrerController
from FlowControl import FlowControl, FlowControlError

# Mocking OceanDirect because the driver file was not provided in this batch.
# In production, replace this with: from oceandirect.OceanDirectAPI import OceanDirectAPI
class MockSpectrometer:
    def get_formatted_spectrum(self): return np.random.rand(100)
    def get_wavelengths(self): return np.linspace(400, 900, 100)
    def set_integration_time(self, t): pass
    def nonlinearity_correct_spectrum2(self, d, s): return s - d

# --- Configuration Constants ---
OB1_SN = '02079C06'
MUX_COM = 'COM11'
MUXD_COM = 'COM5'
STIRRER_COM = 'COM8'

TOTAL_VOLUME = 2000 # uL
AG_CONC = 66
S_CONC = 66
CLEANING_TIME_TOL = 4.25

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Experiment")


def generate_experiment_plan() -> pd.DataFrame:
    """Generates the DataFrame containing all reaction ratios and parameters."""
    # Generate Ratios
    ratios = np.concatenate([
        np.arange(10, 1, -1),
        np.arange(2, 0.9, -0.25),
        np.arange(1, 0.05, -0.1)
    ])
    
    # Create Base DF
    df = pd.DataFrame({'ratio': np.round(ratios, 2)})
    df = df.drop_duplicates().reset_index(drop=True)
    df['dilution_factor'] = 1
    
    # Calculate Volumes
    active_vol = TOTAL_VOLUME / df['dilution_factor']
    df['toluene_volume'] = np.round(TOTAL_VOLUME - active_vol, 2)
    
    # Ag Volume Calculation derived from stoichiometry
    df['Ag_volume'] = (active_vol * df['ratio'] * S_CONC) / (AG_CONC + df['ratio'] * S_CONC)
    df['S_volume'] = (AG_CONC * df['Ag_volume']) / (df['ratio'] * S_CONC)
    
    # Rounding
    df['Ag_volume'] = df['Ag_volume'].round(2)
    df['S_volume'] = df['S_volume'].round(2)
    
    # Metadata
    df['frequency'] = 1
    df['duration'] = 7200
    df.loc[df['ratio'] <= 1, 'duration'] = 600
    df['tube_number'] = 12
    df['reaction_id'] = df.index + 1
    
    return df

def setup_hardware():
    """Initializes all hardware connections."""
    try:
        ob = PressureController(device_name_or_serial=OB1_SN)
        mux = MuxWire(device_name=MUX_COM)
        muxd = MuxDistribution(com_port=MUXD_COM)
        stirrer = StirrerController(port=STIRRER_COM)
        
        flow = FlowControl(ob, mux, muxd)
        
        # Initial Safe State
        logger.info("Setting Safe State...")
        muxd.home()
        muxd.switch_valve(11)
        mux.close_all()
        ob.set_pressure(1, 0)
        ob.set_pressure(2, 0)
        
        return ob, mux, muxd, stirrer, flow
    except Exception as e:
        logger.critical(f"Hardware Init Failed: {e}")
        sys.exit(1)

def main():
    # 1. Init
    ob, mux, muxd, stirrer, flow = setup_hardware()
    
    # Mock Spectrometers (Replace with real init)
    nir = MockSpectrometer()
    vis = MockSpectrometer()
    
    # 2. Calibration (Simplified for Script - normally loaded from file)
    # In a real run, you would load these from a config file
    logger.info("Applying default calibration...")
    flow.update_calibration('ag', slope=452.6, intercept=59.8)
    flow.update_calibration('s', slope=540.0, intercept=72.6)
    flow.update_calibration('tol', slope=580.3, intercept=78.8)
    
    # 3. Generate Plan
    df_plan = generate_experiment_plan()
    logger.info(f"Generated plan with {len(df_plan)} reactions.")
    
    # 4. Data Directory Setup
    base_data_dir = Path("C:/data/arelling") / datetime.now().strftime("%Y-%m-%d")
    base_data_dir.mkdir(parents=True, exist_ok=True)
    
    # Save parameters
    df_plan.to_csv(base_data_dir / "reaction_parameters.csv")
    
    # 5. Main Loop
    stirrer.start_stirring(400)
    
    try:
        for _, row in df_plan.iterrows():
            rid = int(row['reaction_id'])
            ratio = row['ratio']
            
            logger.info(f"--- Starting Reaction {rid} (Ratio {ratio}) ---")
            
            # Create Reaction Folder
            rxn_dir = base_data_dir / f"{rid:02d}_Ratio-{ratio}"
            rxn_dir.mkdir(exist_ok=True)
            
            # --- Experiment Logic ---
            # 1. Pre-Cleaning / Flushing
            # 2. Injection
            logger.info("Injecting Precursors...")
            flow.inject_volume('tol', row['toluene_volume'])
            flow.inject_volume('ag', row['Ag_volume'])
            flow.inject_volume('s', row['S_volume'])
            
            # 3. Measurement Loop (Simplified)
            start_time = time.perf_counter()
            duration = row['duration']
            
            intensities = []
            
            while (time.perf_counter() - start_time) < duration:
                # Trigger Spectrometer
                mux.set_trigger_out(True)
                spec_data = nir.get_formatted_spectrum()
                mux.set_trigger_out(False)
                
                intensities.append(spec_data)
                time.sleep(1) # Frequency delay
                
                # Auto-Stop Logic could go here
            
            # 4. Save Data
            pd.DataFrame(intensities).to_csv(rxn_dir / "spectra.csv")
            logger.info(f"Reaction {rid} complete.")
            
            # 5. Cleanup
            logger.info("Cleaning reactor...")
            flow.collect_product(12, 15) # Waste
            # Rinse
            for _ in range(2):
                flow.inject_toluene(CLEANING_TIME_TOL)
                flow.collect_product(12, 15)

    except KeyboardInterrupt:
        logger.warning("User interrupted experiment.")
    finally:
        logger.info("System Shutdown.")
        flow.stop()
        stirrer.stop_stirring()
        ob.close()
        mux.close()
        muxd.close()
        stirrer.close()

if __name__ == "__main__":
    main()