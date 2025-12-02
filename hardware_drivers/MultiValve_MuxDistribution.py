import time
from ctypes import byref
from typing import Optional
from Elveflow_Core import ElveflowCore, MUX_DRI_Initialization, \
    MUX_DRI_Get_Valve, MUX_DRI_Set_Valve, MUX_DRI_Send_Command, MUX_DRI_Destructor

class MuxDistribution(ElveflowCore):
    """
    Driver for Elveflow MUX Distribution (12-port) or Recirculation (6-port) valves.
    """
    
    def __init__(self, com_port: str):
        """
        Args:
            com_port (str): Serial port (e.g., 'COM3' or 'ASRL1::INSTR').
        """
        super().__init__("MUX Distributor")
        
        print(f"Initializing {self.instrument_name} on {com_port}...")
        error = MUX_DRI_Initialization(com_port.encode('ascii'), byref(self._instr_id))
        
        if self._check_error(error, "Initialization"):
            print(f"✅ {self.instrument_name} initialized. ID: {self._instr_id.value}")
        else:
            self._instr_id.value = -1

    def get_valve(self) -> int:
        """
        Returns the current valve position.
        
        Returns:
            int: Valve Position (1-12) or 0 if moving/busy. Returns -1 on error.
        """
        if self._instr_id.value < 0: return -1
            
        valve = self.C_INT32(-1)
        # Writes position into valve pointer
        error = MUX_DRI_Get_Valve(self._instr_id.value, byref(valve)) 
        
        if self._check_error(error, "Get Valve"):
            return valve.value
        return -1

    def switch_valve(self, valve_number: int, direction: str = "short", timeout: float = 20.0) -> None:
        """
        Blocking call to switch the valve to a target position.
        
        Args:
            valve_number (int): Target position (1-12).
            direction (str): 'short' (Shortest path), 'cw' (Clockwise), 'ccw' (Counter-Clockwise).
            timeout (float): Max wait time in seconds.
        """
        if self._instr_id.value < 0: return

        current = self.get_valve()
        if current == valve_number:
            return

        # print(f"Switching to valve {valve_number} ({direction})...")
        
        # SDK Mapping: 0 = shortest, 1 = clockwise, 2 = counter-clockwise
        mode_map = {'short': 0, 'cw': 1, 'ccw': 2}
        rotation_mode = mode_map.get(direction.lower(), 0)
        
        error = MUX_DRI_Set_Valve(
            self._instr_id.value, 
            self.C_INT32(valve_number), 
            self.C_UINT16(rotation_mode)
        )
        
        if not self._check_error(error, "Set Valve"):
            return

        # Polling loop
        start_t = time.time()
        while (time.time() - start_t) < timeout:
            time.sleep(0.2)
            state = self.get_valve()
            if state == valve_number:
                print(f"✅ Reached valve {valve_number}")
                return
            
        print(f"❌ Timeout switching to valve {valve_number}")

    def home(self, timeout: float = 20.0) -> None:
        """
        Performs the homing sequence to calibrate position 1.
        """
        if self._instr_id.value < 0: return
        
        print("🔄 Homing valve...")
        ans = self.C_CHAR_40()
        
        # Command 0 = Home
        error = MUX_DRI_Send_Command(self._instr_id.value, self.C_UINT16(0), ans, 40)
        
        if self._check_error(error, "Homing"):
            print("Home command sent. Waiting for completion...")
            time.sleep(0.5) 
            
            start_t = time.time()
            while (time.time() - start_t) < timeout:
                state = self.get_valve()
                
                # State 0 = Busy/Moving. State > 0 = Stopped at a valid position.
                if state > 0:
                    print(f"✅ Homing complete. Reached position {state}.")
                    return
                    
                time.sleep(0.5)
                
            print("❌ Homing timed out.")

    def get_serial(self) -> Optional[str]:
        """Queries the hardware serial number."""
        if self._instr_id.value < 0: return None
        
        ans = self.C_CHAR_40()
        # Command 1 = Get Serial
        error = MUX_DRI_Send_Command(self._instr_id.value, self.C_UINT16(1), ans, 40)
        
        if self._check_error(error, "Get Serial"):
            return ans.value.decode('ascii')
        return None

    def close(self) -> None:
        """Releases the instrument handle."""
        if self._instr_id.value >= 0:
            error = MUX_DRI_Destructor(self._instr_id.value)
            self._check_error(error, "Destructor")
            self._instr_id.value = -1