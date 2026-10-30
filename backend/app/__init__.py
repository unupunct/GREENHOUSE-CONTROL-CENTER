"""Greenhouse Control Center backend."""

import warnings

# Modbus register addresses are called "register" in the API; pydantic warns that this shadows a BaseModel method (harmless here).
warnings.filterwarnings("ignore", message='Field name "register"')

__version__ = "0.9.0"
