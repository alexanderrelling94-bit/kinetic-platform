import time
import logging
from typing import Optional, Dict, Tuple, Literal
import numpy as np
from scipy.stats import linregress

# Import Type definitions for IntelliSense
from Hardware_Drivers.PressureController_OB import PressureController
from Hardware_Drivers.ValveController_MuxWire import MuxWire
from Hardware_Drivers.MultiValve_MuxDistribution import MuxDistribution

# Configure Logging
logger = logging.getLogger(__name__)

class FlowControlError(RuntimeError):
    """Custom exception for critical flow control failures."""
    pass

class FlowControl:
    """
    High-Level Orchestrator for Liquid Handling.
    
    Manages the interaction between Pressure Controllers and Valves to 
    execute complex liquid handling protocols (Injection, Cleaning, Mixing).
    """

    def __init__(self, 
                 ob: PressureController, 
                 mux: MuxWire, 
                 muxd: MuxDistribution,
                 s_slope: float = 0.0, s_intercept: float = 0.0, 
                 ag_slope: float = 0.0, ag_intercept: float = 0.0,
                 tol_slope: float = 0.0, tol_intercept: float = 0.0):
        
        # Hardware References
        self.ob = ob
        self.mux = mux
        self.muxd = muxd
        self.retry_count = 3 
        
        # Calibration Constants (Volume = slope * time + intercept)
        self.s_slope = s_slope
        self.s_intercept = s_intercept
        self.ag_slope = ag_slope
        self.ag_intercept = ag_intercept
        self.tol_slope = tol_slope
        self.tol_intercept = tol_intercept
        
    # --- Internal Helpers ---
    
    def _ensure_p1_pressure(self, pressure: float, wait: float = 5.0) -> None:
        """Sets P1 pressure only if the target differs, saving bus traffic."""
        if self.ob.get_setpoint(1) != pressure:
            self.ob.set_pressure(1, pressure)
            if pressure != 0:
                time.sleep(wait)

    def _toggle_valve_retry(self, valve_number: int, desired_state: int, delay: float) -> None:
        """
        Switches a valve with robust retry logic.
        Raises FlowControlError if hardware fails to confirm state.
        """
        is_open = (desired_state == 1)
        
        for attempt in range(self.retry_count):
            self.mux.toggle(valve_number, is_open) 
            time.sleep(delay)
            
            # Verify state (Read-back)
            if self.mux.get_valve_state(valve_number) == desired_state:
                return 
            
            logger.warning(f"Valve {valve_number} switching retry ({attempt + 1}/{self.retry_count})")
            time.sleep(0.5)

        raise FlowControlError(f"Critical: Valve {valve_number} stuck. Expected state {desired_state}.")

    # --- Core Valve Controls ---

    def stop(self) -> None:
        """
        Emergency Stop / Safe State.
        Vents all pressure, closes valves, and resets distribution valve.
        """
        logger.info("Initiating Emergency Stop / Safe State...")
        self.mux.set_trigger_out(False)
        self.mux.close_all() 
        self.ob.set_pressure(1, 0)
        self.ob.set_pressure(2, 0)
        self.muxd.switch_valve(11, direction='short')

    def switch_v1_source(self, source: Literal['tol', 'pre'], delay: float = 1.0) -> None:
        """
        Switches Valve 1 (Source Selection).
        
        Args:
            source: 'tol' (Toluene) or 'pre' (Precursor).
        """
        source = source.lower()
        if source not in ("tol", "pre"):
            raise ValueError("Source must be 'tol' or 'pre'")
            
        target = 0 if source == "tol" else 1
        
        # Optimize: Only switch if needed
        if self.mux.get_valve_state(1) != target:
            # Safety: Vent before switching input lines
            if self.ob.get_setpoint(1) != 0:
                self.ob.set_pressure(1, 0)
                time.sleep(3) 
            
            self._toggle_valve_retry(1, target, delay)

    def switch_v2_outlet(self, destination: Literal['waste', 'tube'], delay: float = 1.0) -> None:
        """
        Switches Valve 2 (Outlet Selection).
        
        Args:
            destination: 'waste' or 'tube'.
        """
        destination = destination.lower()
        if destination not in ("waste", "tube"):
            raise ValueError("Destination must be 'waste' or 'tube'")
            
        target = 0 if destination == "waste" else 1
        
        if self.mux.get_valve_state(2) != target:
            # Safety: Vent before switching output
            if self.ob.get_setpoint(2) != 0:
                self.ob.set_pressure(2, 0)
                time.sleep(5) 
                
            self._toggle_valve_retry(2, target, delay)

    def pulse_valve(self, valve_number: int, duration: float, delay: float = 0.05) -> None:
        """
        Opens a valve for a precise duration (Time-Pressure Injection).
        Uses busy-wait for sub-second precision.
        """
        self._toggle_valve_retry(valve_number, 1, delay) 
        
        # High precision timing
        start = time.perf_counter()
        while time.perf_counter() - start < duration:
            pass 
            
        self._toggle_valve_retry(valve_number, 0, delay)

    # --- Protocol Wrappers ---

    def inject_toluene(self, duration: float) -> None:
        """Injects Toluene via Valve 3."""
        if self.mux.get_valve_state(1) != 0: 
            self.switch_v1_source("tol")
        self._ensure_p1_pressure(1000)
        self.pulse_valve(3, duration)

    def inject_precursor_s(self, duration: float) -> None:
        """Injects Sulfur Precursor via Valve 4."""
        if self.mux.get_valve_state(1) != 1: 
            self.switch_v1_source("pre")
        self._ensure_p1_pressure(1000)
        self.pulse_valve(4, duration)

    def inject_precursor_ag(self, duration: float) -> None:
        """Injects Silver Precursor via Valve 5."""
        if self.mux.get_valve_state(1) != 1: 
            self.switch_v1_source("pre")
        self._ensure_p1_pressure(1000)
        self.pulse_valve(5, duration)

    def collect_product(self, tube_number: int, duration: float) -> None:
        """
        Moves product from mixing zone to collection tube or waste.
        Uses vacuum (Negative Pressure) on P2.
        """
        target = "waste" if tube_number == 12 else "tube"
        self.switch_v2_outlet(target)
        
        # Move Distributor Valve if needed
        if self.muxd.get_valve() != tube_number:
            self.ob.set_pressure(2, 0) # Safety vent
            time.sleep(5)
            self.muxd.switch_valve(tube_number, direction='cw')
            time.sleep(5) 
            
        self.ob.set_pressure(2, -1000) # Vacuum pull
        time.sleep(duration)
        self.ob.set_pressure(2, 0)     # Vent
        time.sleep(10) 

    # --- Volumetric Logic (Calibration Application) ---

    def update_calibration(self, target: str, slope: float, intercept: float) -> None:
        """Updates calibration constants for a specific fluid."""
        t = target.lower()
        if t == 's':
            self.s_slope, self.s_intercept = slope, intercept
        elif t == 'ag':
            self.ag_slope, self.ag_intercept = slope, intercept
        elif t in ['tol', 'toluene']:
            self.tol_slope, self.tol_intercept = slope, intercept
        else:
            logger.warning(f"Unknown calibration target '{target}'")
            return
        logger.info(f"Calibration updated for {target}: {slope:.4f}x + {intercept:.4f}")

    def inject_volume(self, target: str, ul: float) -> None:
        """
        Injects a specific volume (uL) by calculating the required time based on calibration.
        """
        t = target.lower()
        
        if t == 's':
            slope, inter = self.s_slope, self.s_intercept
            func = self.inject_precursor_s
        elif t == 'ag':
            slope, inter = self.ag_slope, self.ag_intercept
            func = self.inject_precursor_ag
        elif t in ['tol', 'toluene']:
            slope, inter = self.tol_slope, self.tol_intercept
            func = self.inject_toluene
        else:
            logger.error(f"Unknown target {target}")
            return

        if slope == 0.0:
            logger.error(f"Slope is 0 for {target}. Perform calibration first.")
            return

        # V = slope * t + intercept  =>  t = (V - intercept) / slope
        duration = (ul - inter) / slope
        
        if duration < 0:
            logger.warning(f"Calculated negative duration ({duration:.3f}s) for {ul}uL. Skipping.")
            return

        func(duration)
    
    # --- Calibration Utility ---
    
    @staticmethod
    def calculate_calibration(data_dict: Dict[float, list], density: float, name: str) -> Tuple[float, float]:
        """
        Performs linear regression on mass vs. time data.
        
        Args:
            data_dict: Dictionary {time_seconds: [mass1, mass2...]}
            density: Fluid density in g/mL
            name: Name of the fluid for logging
            
        Returns:
            (slope, intercept)
        """
        all_times = []
        all_volumes = []
        
        for t, masses in data_dict.items():
            if not isinstance(masses, list): 
                masses = [masses]
            for m in masses:
                all_times.append(t)
                all_volumes.append(m / density) # Convert mass to volume

        slope, intercept, r_val, _, _ = linregress(all_times, all_volumes)
        
        logger.info(f"{name} Calibration: V = {slope:.3f}t + {intercept:.3f} (R²: {r_val**2:.4f})")
        
        return slope, intercept

    # --- Backward Compatibility (Deprecation Warnings could be added) ---
    def S_cuvette_volume(self, v): self.inject_volume('s', v)
    def Ag_cuvette_volume(self, v): self.inject_volume('ag', v)
    def Tol_cuvette_volume(self, v): self.inject_volume('tol', v)
    def switch_v1_tol_or_pre(self, s): self.switch_v1_source(s)
    def S_cuvette(self, d): self.inject_precursor_s(d)
    def Ag_cuvette(self, d): self.inject_precursor_ag(d)