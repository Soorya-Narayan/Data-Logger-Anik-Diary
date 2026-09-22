"""
Base PLC Client Interface.
Provides a unified contract for both Mock and Live (pylogix) PLC drivers.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any


class BasePLCClient(ABC):
    """Abstract interface for reading process telemetry from a PLC."""

    @abstractmethod
    def connect(self) -> bool:
        """
        Establish a connection to the PLC.
        Returns True if connected successfully, False otherwise.
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Gracefully terminate connection to the PLC."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if client currently has a valid connection."""
        pass

    @abstractmethod
    def read_tags(self) -> Dict[str, Any]:
        """
        Poll all configured logical tags from the PLC.
        
        Returns:
            Dict[str, Any]: Dictionary keyed by logical field names, e.g.:
            {
                "timestamp": "2026-09-22T10:45:00",
                "milk_flow": 32450.5,
                "holding_in_temp": 81.2,
                "holding_out_temp": 80.8,
                "product": "TONED_MILK",
                "status": "PRODUCTION ACCEPTED: FDV-1 Forward & FDV-2 Forward",
                "fdv1_status": 1,
                "fdv1_reason": "All Ok",
                "fdv2_status": 1,
                "fdv2_reason": "All Ok",
                "cip_status": 0,
                "cip_step": "None",
                "fdv_feedback": 3
            }
            
        Raises:
            ConnectionError: When communication fails or drops.
        """
        pass
