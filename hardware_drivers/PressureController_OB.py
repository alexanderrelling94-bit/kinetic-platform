from ctypes import byref
from typing import Dict, Tuple, Optional
from Elveflow_Core import ElveflowCore, OB1_Initialization, OB1_Add_Sens, \
    OB1_Set_Filter, OB1_Set_Press, OB1_Set_Sens, OB1_Get_All_Data, \
    OB1_Calib_Load, OB1_Calib, OB1_Calib_Save, OB1_Set_Trig, OB1_Get_Trig, \
    OB1_Reset_Instr, OB1_Destructor, PID_Add_Remote

class PressureController(ElveflowCore):
    """
    High-level driver for the Elveflow OB1 Pressure Controller.
    
    Features:
    - Pressure setting & reading
    - Flow sensor integration
    - PID Feedback loops
    - Calibration management
    - Trigger I/O
    """

    def __init__(self, device_name_or_serial: str, num_pressure_channels: int = 4, num_sensors: int = 4):
        """
        Args:
            device_name_or_serial (str): The serial number (e.g., '01234') or NI device name.
            num_pressure_channels (int): Number of pressure regulators available.
            num_sensors (int): Number of flow sensor ports available.
        """
        super().__init__("OB1")
        
        # Internal Memory for Setpoints to minimize unnecessary hardware calls
        self._setpoints: Dict[int, float] = {ch: 0.0 for ch in range(1, 5)} 
        
        print(f"Initializing {self.instrument_name} ({device_name_or_serial})...")
        
        # Call SDK Initialization
        error = OB1_Initialization(
            device_name_or_serial.encode('ascii'), 
            self.C_UINT16(num_pressure_channels), 
            self.C_UINT16(num_sensors),
            self.C_UINT16(0), 
            self.C_UINT16(0),
            byref(self._instr_id)
        )
        
        if self._check_error(error, "Initialization"):
            print(f"✅ {self.instrument_name} initialized. ID: {self._instr_id.value}")
        else:
            self._instr_id.value = -1

    def add_flow_sensor(self, sensor_ch: int, sensor_type: int, digital: bool = True, 
                       medium: int = 0, resolution: int = 16) -> None:
        """
        Configures a flow sensor on a specific channel.
        
        Args:
            sensor_ch (int): Channel index (1-4).
            sensor_type (int): SDK Sensor ID (e.g. 5 for FS5).
            digital (bool): True for digital sensors, False for analog.
            medium (int): Calibration medium. 0=H2O, 1=Isopropanol, 2=Acetone.
            resolution (int): Sensor resolution bits (default: 16).
        """
        if self._instr_id.value < 0: return

        is_digital = 1 if digital else 0
        
        error = OB1_Add_Sens(
            self._instr_id.value,
            self.C_INT32(sensor_ch),
            self.C_UINT16(sensor_type),
            self.C_UINT16(is_digital),
            self.C_UINT16(medium), 
            self.C_UINT16(resolution),
            self.C_DOUBLE(0)
        )
        self._check_error(error, f"Add Sensor Ch{sensor_ch} (Medium: {medium})")

    def set_filter(self, channel: int, value: float) -> None:
        """
        Sets the acquisition filter (low-pass).
        
        Args:
            channel (int): Regulator or Sensor channel (1-4).
            value (float): Filter constant [0.001, 1.0]. Lower is smoother but slower.
        """
        if self._instr_id.value < 0: return
        
        # Clamp value strictly to SDK range to prevent crashes
        value = max(0.001, min(1.0, value))
        
        error = OB1_Set_Filter(
            self._instr_id.value, 
            self.C_INT32(channel), 
            self.C_DOUBLE(value)
        )
        self._check_error(error, f"Set Filter Ch{channel} -> {value}")

    def setup_pid(self, regulator_ch: int, sensor_ch: int, P: float, I: float) -> None:
        """Enables hardware-based PID control loop."""
        if self._instr_id.value < 0: return

        error = PID_Add_Remote(
            self._instr_id.value,
            self.C_INT32(regulator_ch),
            self._instr_id.value, 
            self.C_INT32(sensor_ch),
            self.C_DOUBLE(P),
            self.C_DOUBLE(I),
            self.C_INT32(1) # Running = True
        )
        
        if self._check_error(error, f"Setup PID R{regulator_ch}->S{sensor_ch}"):
            print(f"✅ PID Active: Regulator {regulator_ch} controlled by Sensor {sensor_ch}")

    def set_pressure(self, channel: int, mbar: float) -> None:
        """Sets pressure in mbar and updates internal state."""
        if self._instr_id.value < 0: return
        
        error = OB1_Set_Press(self._instr_id.value, self.C_INT32(channel), self.C_DOUBLE(mbar))
        
        if self._check_error(error, f"Set Pressure Ch{channel}"):
            self._setpoints[channel] = mbar

    def set_target(self, channel: int, value: float) -> None:
        """Sets target for Flow Control (if PID is active) or Pressure."""
        if self._instr_id.value < 0: return
        
        error = OB1_Set_Sens(self._instr_id.value, self.C_INT32(channel), self.C_DOUBLE(value))
        self._check_error(error, f"Set Target Ch{channel} -> {value}")

    def get_setpoint(self, channel: int) -> float:
        """Returns the last known setpoint (cached) to avoid bus traffic."""
        return self._setpoints.get(channel, 0.0)

    def get_data(self) -> Optional[Dict[int, Tuple[float, float]]]:
        """
        Reads all channels synchronously.
        
        Returns:
            dict: {Channel_ID: (Pressure, Flow)} or None if error.
        """
        if self._instr_id.value < 0: return None
        
        data = [self.C_DOUBLE() for _ in range(8)]
        
        # Pointers to 8 doubles (4x Pressure, 4x Sensor)
        error = OB1_Get_All_Data(self._instr_id.value, 
                                 byref(data[0]), byref(data[1]),
                                 byref(data[2]), byref(data[3]),
                                 byref(data[4]), byref(data[5]),
                                 byref(data[6]), byref(data[7]))
        
        if self._check_error(error, "Get Data"):
            return {
                1: (data[0].value, data[1].value),
                2: (data[2].value, data[3].value),
                3: (data[4].value, data[5].value),
                4: (data[6].value, data[7].value),
            }
        return None

    def calibrate(self, path: str, load_existing: bool = True) -> None:
        """
        Handles instrument calibration.
        
        Args:
            path (str): File path for the calibration file (.cal).
            load_existing (bool): If True, loads file. If False, runs new calibration.
        """
        if self._instr_id.value < 0:
            print("❌ Instrument ID invalid. Cannot calibrate.")
            return

        c_path = path.encode('ascii')
        
        if load_existing:
            print(f"Loading calibration from {path}...")
            error = OB1_Calib_Load(self._instr_id.value, c_path)
            self._check_error(error, "Calibration Load")
            
        else:
            print("Starting NEW calibration (WARNING: Ensure ALL channels are blocked!)...")
            
            # 1. Run Calibration (In Memory)
            calib_error = OB1_Calib(self._instr_id.value)
            
            if calib_error == 0: 
                print("Physical calibration successful. Saving to file...")
                # 2. Save to Disk
                save_error = OB1_Calib_Save(self._instr_id.value, c_path)
                self._check_error(save_error, "Calibration Save")
                
                if save_error == 0:
                    # 3. Verification Self-Test
                    print("Performing self-test (Reloading file)...")
                    verify_error = OB1_Calib_Load(self._instr_id.value, c_path)
                    
                    if verify_error == 0:
                         print("✅ VERIFICATION PASSED: File valid.")
                    else:
                         print(f"❌ VERIFICATION FAILED: Error {verify_error}.")
            else:
                self._check_error(calib_error, "Calibration Run")

    def set_trigger_out(self, state: bool) -> None:
        """Sets the digital trigger output (0V / 5V)."""
        if self._instr_id.value < 0: return
        val = 1 if state else 0
        error = OB1_Set_Trig(self._instr_id.value, self.C_INT32(val)) 
        self._check_error(error, "Set Trig Out")

    def get_trigger_in(self) -> Optional[bool]:
        """Reads the digital trigger input."""
        if self._instr_id.value < 0: return None
        
        trig_val = self.C_INT32()
        error = OB1_Get_Trig(self._instr_id.value, byref(trig_val))
        
        if self._check_error(error, "Get Trig In"):
            return True if trig_val.value == 1 else False
        return None

    def reset(self) -> None:
        """Resets instrument communication."""
        if self._instr_id.value >= 0:
            print("⚠️ Resetting OB1...")
            OB1_Reset_Instr(self._instr_id.value)

    def close(self) -> None:
        """Releases the instrument handle."""
        if self._instr_id.value >= 0:
            error = OB1_Destructor(self._instr_id.value)
            self._check_error(error, "Destructor")
            self._instr_id.value = -1