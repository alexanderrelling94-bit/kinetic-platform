import os
import sys
from ctypes import c_int32, c_uint16, c_double, c_char, CDLL
from typing import Optional, Union, Any
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Dynamic import logic for the vendor wrapper
# Assumes 'Elveflow64.py' is in a subfolder named 'elveflow' relative to this script
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ELVEFLOW_DIR = os.path.join(CURRENT_DIR, 'elveflow')

if ELVEFLOW_DIR not in sys.path:
    sys.path.append(ELVEFLOW_DIR)

try:
    # Attempt to import the vendor-provided wrapper
    from Elveflow64 import * # type: ignore
except ImportError:
    logger.critical(f"Could not import 'Elveflow64.py'. Ensure it is located in: {ELVEFLOW_DIR}")
    sys.exit(1)


class ElveflowCore:
    """
    Base abstraction class for all Elveflow devices.
    
    Provides standardized error checking, type definitions, and Context Manager 
    support to ensure resources are released properly.
    """
    
    # Common C types aliases for cleaner code in child classes
    C_INT32 = c_int32
    C_UINT16 = c_uint16
    C_DOUBLE = c_double
    C_CHAR_40 = c_char * 40
    
    ERROR_CODE_SUCCESS = 0

    def __init__(self, instrument_name: str = "Elveflow_Device"):
        """
        Initialize the base device wrapper.

        Args:
            instrument_name (str): A human-readable name for logging/debugging.
        """
        self.instrument_name = instrument_name
        self._instr_id = self.C_INT32(-1) # Standardized ID variable for the DLL handle
        self.logger = logging.getLogger(instrument_name)

    def _check_error(self, error_code: Union[int, Any], context: str = "Operation") -> bool:
        """
        Validates the return code from C-DLL calls.

        Args:
            error_code: The return value from the SDK function (int or ctypes object).
            context (str): Description of the operation being performed (for logging).

        Returns:
            bool: True if the operation was successful, False otherwise.
        """
        # Robustly extract integer value from ctypes object or raw int
        if hasattr(error_code, 'value'):
            code = error_code.value
        else:
            try:
                code = int(error_code)
            except (ValueError, TypeError):
                self.logger.error(f"Unknown error format in '{context}': {error_code}")
                return False

        if code != self.ERROR_CODE_SUCCESS:
            self.logger.error(f"Error in '{context}': Code {code}")
            return False
            
        return True

    def close(self) -> None:
        """
        Placeholder for the specific destructor. 
        Must be implemented by child classes to release hardware handles.
        """
        raise NotImplementedError("Child class must implement 'close()'")

    # --- Context Manager Protocol ---
    def __enter__(self):
        """Enables usage of 'with' statement."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Ensures close() is called when exiting a 'with' block, preventing resource locks."""
        self.close()