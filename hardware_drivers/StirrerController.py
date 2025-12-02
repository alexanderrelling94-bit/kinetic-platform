import serial
import time
import logging
from typing import Tuple, Optional, List, Union

# Configure logging
logger = logging.getLogger(__name__)

class StirrerController:
    """
    Driver for LLG uniSTIRRER 5 (Binary Protocol).
    
    Handles low-level binary communication (Hex-based) to control 
    stirring speed (RPM) and hotplate temperature.
    """

    def __init__(self, port: str = 'COM8', baudrate: int = 9600, timeout: float = 2.0):
        """
        Initialize the Stirrer Controller.

        Args:
            port (str): The COM port (e.g., 'COM8' or '/dev/ttyUSB0').
            baudrate (int): Connection speed (default: 9600).
            timeout (float): Read timeout in seconds.
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser: Optional[serial.Serial] = None
        self._connect()

    def _connect(self) -> None:
        """Internal method to establish the serial connection."""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
                timeout=self.timeout
            )
            logger.info(f"Stirrer connected on {self.port}")
        except serial.SerialException as e:
            logger.error(f"Failed to connect stirrer on {self.port}: {e}")
            raise e

    def close(self) -> None:
        """Closes the serial connection safely, stopping hardware first."""
        if self.ser and self.ser.is_open:
            try:
                # Try to stop stirring/heating before disconnect (Safety)
                self.stop_stirring()
                self.stop_heating()
            except Exception as e:
                logger.warning(f"Error during safe shutdown: {e}")
            
            self.ser.close()
            logger.info(f"Stirrer connection on {self.port} closed.")

    # --- 1. Protocol Helpers ---

    def _calculate_checksum(self, instruction_code: int, data_frames: List[int]) -> int:
        """Calculates the 8-bit checksum required by the device protocol."""
        checksum = instruction_code
        for frame in data_frames:
            checksum = (checksum + frame) & 0xFF
        return checksum

    def _get_high_low_bytes(self, number: int) -> Tuple[int, int]:
        """Splits a 16-bit integer into (High Byte, Low Byte)."""
        return (number >> 8) & 0xFF, number & 0xFF

    def _combine_bytes(self, high_byte: Union[bytes, int], low_byte: Union[bytes, int]) -> int:
        """Combines High and Low bytes back into a 16-bit integer."""
        h = high_byte[0] if isinstance(high_byte, bytes) else high_byte
        l = low_byte[0] if isinstance(low_byte, bytes) else low_byte
        return (h << 8) | l

    def _send_command(self, instruction_code: int, data_frames: List[int], response_length: int) -> Optional[bytes]:
        """
        Sends a binary command packet and validates the response.
        
        Packet Structure: [Prefix (0xFE)] [Instruction] [Data...] [Checksum]
        """
        if not self.ser or not self.ser.is_open:
            logger.error("Attempted command on closed connection.")
            return None

        # 1. Clear Buffer to ensure fresh response
        self.ser.reset_input_buffer()

        # 2. Construct Packet
        prefix = 0xFE
        checksum = self._calculate_checksum(instruction_code, data_frames)
        packet = [prefix, instruction_code] + data_frames + [checksum]
        
        # 3. Send
        try:
            self.ser.write(bytes(packet))
            time.sleep(0.1) # Wait for hardware processing
            
            # 4. Read Response
            response = self.ser.read(response_length)
            if len(response) < response_length:
                logger.warning(f"Command 0x{instruction_code:02X} timed out (received {len(response)}/{response_length} bytes)")
                return None

            # 5. Validate Prefix (0xFD is standard response prefix)
            if response[0] != 0xFD:
                logger.warning(f"Invalid Response Prefix: {hex(response[0])}")
                return None
                
            # Return data payload (strip prefix, echo, checksum)
            return response[2:-1]
            
        except serial.SerialException as e:
            logger.error(f"Serial communication error: {e}")
            return None

    # --- 2. Core Commands ---

    def cmd_hello(self) -> int:
        """Handshake command (0xA0). Returns 1 if successful."""
        resp = self._send_command(0xA0, [0x00, 0x00, 0x00], 6)
        return 1 if (resp and resp[0] == 0x00) else 0

    def cmd_info(self) -> Tuple[int, int]:
        """
        Queries status (0xA1).
        Returns: (stirrer_active (0/1), heater_active (0/1))
        """
        resp = self._send_command(0xA1, [0x00, 0x00, 0x00], 12)
        if not resp: 
            return -1, -1
        
        # Byte logic determined via reverse engineering
        stirrer_on = 1 if resp[1] == 0x00 else 0
        heater_on = 1 if resp[2] == 0x00 else 0
        return stirrer_on, heater_on

    def cmd_sta(self) -> Tuple[int, int, float, float]:
        """
        Queries current values (0xA2).
        Returns: (Set Speed, Real Speed, Set Temp, Real Temp)
        """
        resp = self._send_command(0xA2, [0x00, 0x00, 0x00], 15)
        if not resp or len(resp) < 8:
            return 0, 0, 0.0, 0.0
            
        speed_set = self._combine_bytes(resp[0], resp[1])
        real_speed = self._combine_bytes(resp[2], resp[3])
        # Temperature is scaled by 10 (e.g., 255 = 25.5°C)
        temp_set = self._combine_bytes(resp[4], resp[5]) / 10.0 
        real_temp = self._combine_bytes(resp[6], resp[7]) / 10.0
        
        return speed_set, real_speed, temp_set, real_temp

    def set_speed(self, speed: int) -> bool:
        """Sets target RPM (Command 0xB1)."""
        h, l = self._get_high_low_bytes(speed)
        resp = self._send_command(0xB1, [h, l, 0x00], 6)
        return bool(resp and resp[0] == 0x00)

    def set_temp(self, temp_int: int) -> bool:
        """Sets internal temperature integer value (Command 0xB2)."""
        h, l = self._get_high_low_bytes(temp_int)
        resp = self._send_command(0xB2, [h, l, 0x00], 6)
        return bool(resp and resp[0] == 0x00)

    # --- 3. High Level Control ---

    def start_stirring(self, speed: int = 300) -> None:
        """
        Starts stirring at the specified RPM. 
        Includes check to prevent unnecessary commands if already running.
        """
        current_status, _ = self.cmd_info()
        
        # If already on but speed differs, restart logic (device specific quirk)
        if current_status == 1:
            curr_set, _, _, _ = self.cmd_sta()
            if curr_set != speed:
                self.stop_stirring()
                time.sleep(0.5)
        
        if self.set_speed(speed):
            logger.info(f"Stirring set to {speed} RPM")
        else:
            logger.error("Failed to set stirring speed")

    def stop_stirring(self) -> None:
        """Stops the stirrer (Sets RPM to 0)."""
        if self.set_speed(0):
            logger.info("Stirring Stopped")

    def set_temperature(self, temp_c: float) -> None:
        """
        Sets target temperature in °C.
        """
        temp_val = int(temp_c * 10) # Convert 25.5 -> 255 for protocol
        
        _, current_heat = self.cmd_info()
        if current_heat == 1:
            _, _, curr_set, _ = self.cmd_sta()
            # If target changed significantly, reset heating logic
            if abs(curr_set - temp_c) > 0.1:
                self.stop_heating()
                time.sleep(0.5)

        if self.set_temp(temp_val):
            logger.info(f"Temperature set to {temp_c}°C")
        else:
            logger.error("Failed to set temperature")

    def start_heating(self, temp_c: float) -> None:
        """Alias for set_temperature."""
        self.set_temperature(temp_c)

    def stop_heating(self) -> None:
        """Sets temperature to a safe idle value (25°C)."""
        if self.set_temp(250): # 25.0°C
            logger.info("Heating Stopped (Target: 25°C)")

    # --- Context Manager Support ---
    def __enter__(self): 
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb): 
        self.close()