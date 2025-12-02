from ctypes import byref, create_string_buffer
from Elveflow_Core import *

class MuxWire(ElveflowCore):
    """
    Manages the Elveflow MUX Wire (16 individual valves).
    """
    MAX_VALVES = 16

    def __init__(self, device_name="Dev1"):
        # MUX Wire uses NI-DAQ naming (e.g. "Dev1")
        super().__init__("MUX Wire")
        
        self._valve_states = (self.C_INT32 * self.MAX_VALVES)(0)

        c_name = create_string_buffer(device_name.encode('ascii'))
        print(f"Initializing {self.instrument_name} on {device_name}...")
        
        error = MUX_Initialization(c_name, byref(self._instr_id))
        
        if self._check_error(error, "Initialization"):
            print(f"✅ {self.instrument_name} initialized. ID: {self._instr_id.value}")
            self.close_all()
        else:
            self._instr_id.value = -1

    def configure_valve_type(self, valve_idx: int, valve_type: int):
        """Configures valve type (SDK: MUX_Set_valves_Type)."""
        if self._instr_id.value < 0: return

        error = MUX_Set_valves_Type(
            self._instr_id.value, 
            self.C_INT32(valve_idx), 
            self.C_INT32(valve_type)
        )
        self._check_error(error, f"Set Valve Type Ch{valve_idx}")

    def get_valve_type(self, valve_idx: int):
        """Reads valve type (SDK: MUX_Get_valves_Type)."""
        if self._instr_id.value < 0: return None
        
        # Array to hold types (SDK requirement)
        types_array = (self.C_INT32 * 16)(0)
        
        # Note: SDK takes len=16, implies it fills the array
        error = MUX_Get_valves_Type(self._instr_id.value, types_array, 16)
        
        if self._check_error(error, "Get Valve Types"):
            # Check range
            if 1 <= valve_idx <= 16:
                return types_array[valve_idx-1]
        return None

    def set_all(self, states: list):
        """Sets all 16 valves (SDK: MUX_Wire_Set_all_valves)."""
        if len(states) != 16:
            print("❌ Need exactly 16 states.")
            return

        for i, val in enumerate(states):
            self._valve_states[i] = self.C_INT32(val)
            
        error = MUX_Wire_Set_all_valves(self._instr_id.value, self._valve_states, 16)
        self._check_error(error, "Set All Valves")

    def toggle(self, valve_idx: int, open_valve: bool):
        """Sets single valve using array method."""
        if not (1 <= valve_idx <= 16): return
        
        self._valve_states[valve_idx-1] = self.C_INT32(1 if open_valve else 0)
        error = MUX_Wire_Set_all_valves(self._instr_id.value, self._valve_states, 16)
        self._check_error(error, f"Toggle Valve {valve_idx}")

    def set_individual_valve(self, valve_idx: int, state: bool):
        """Sets single valve using direct method (SDK: MUX_Set_indiv_valve)."""
        if self._instr_id.value < 0: return
        
        val = 1 if state else 0
        error = MUX_Set_indiv_valve(
            self._instr_id.value, 
            self.C_INT32(valve_idx), 
            self.C_INT32(0), 
            self.C_INT32(val)
        )
        
        if self._check_error(error, f"Set Indiv Valve {valve_idx}"):
            self._valve_states[valve_idx-1] = self.C_INT32(val)

    def get_valve_state(self, valve_idx: int):
        """Reads actual valve state from device (SDK: MUX_Get_valves_state)."""
        if self._instr_id.value < 0: return None
        
        state_array = (self.C_INT32 * 16)(0)
        error = MUX_Get_valves_state(self._instr_id.value, state_array, 16)
        
        if self._check_error(error, "Get Valve States"):
            if 1 <= valve_idx <= 16:
                return state_array[valve_idx-1]
        return None

    def set_trigger_out(self, high: bool):
        """Sets trigger OUT (SDK: MUX_Set_Trig)."""
        if self._instr_id.value < 0: return
        val = 1 if high else 0
        # FIXED: Access .value of instr_id
        error = MUX_Set_Trig(self._instr_id.value, self.C_INT32(val))
        self._check_error(error, "Set Trigger Out")

    def get_trigger_in(self):
        """Reads trigger IN (SDK: MUX_Get_Trig)."""
        if self._instr_id.value < 0: return None
        
        trig_val = self.C_INT32()
        error = MUX_Get_Trig(self._instr_id.value, byref(trig_val))
        
        if self._check_error(error, "Get Trig In"):
            return True if trig_val.value == 1 else False
        return None

    def close_all(self):
        self.set_all([0]*16)

    def close(self):
        """SDK: MUX_Destructor."""
        if self._instr_id.value >= 0:
            error = MUX_Destructor(self._instr_id.value)
            self._check_error(error, "Destructor")
            self._instr_id.value = -1