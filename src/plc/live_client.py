"""
Live PLC Client for Allen Bradley Micro850 (2080-LC70-24QBB) using pylogix.
Communicates via EtherNet/IP CIP Symbolic Addressing (Global Variables).
"""

import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional

try:
    from pylogix import PLC
except ImportError:
    PLC = None

from src.plc.base import BasePLCClient

logger = logging.getLogger("LivePLCClient")


class LivePLCClient(BasePLCClient):
    """
    Production driver for Allen-Bradley Micro850 PLC.
    Configured with Micro800=True for CCW Global Variable CIP access.
    """

    def __init__(self, config: dict, tags_config: dict):
        self.config = config
        self.tags_config = tags_config.get("tags", {})
        
        plc_cfg = config.get("plc", {})
        self.ip = plc_cfg.get("ip", "192.168.1.50")
        self.slot = plc_cfg.get("slot", 0)
        self.timeout = plc_cfg.get("timeout", 3.0)

        self._plc: Optional[Any] = None
        self._connected = False

        # Inverted mapping: PLC Tag Name -> Logical Tag Name
        self._plc_to_logical = {
            meta["plc_tag"]: logical_key
            for logical_key, meta in self.tags_config.items()
        }
        self._tag_list = list(self._plc_to_logical.keys())

    def connect(self) -> bool:
        """Establish session with Allen-Bradley Micro850."""
        if PLC is None:
            raise ImportError(
                "pylogix package is not installed. Run 'pip install pylogix' on the Raspberry Pi."
            )

        try:
            logger.info("Initializing EtherNet/IP connection to Micro850 @ %s...", self.ip)
            self._plc = PLC()
            self._plc.IPAddress = self.ip
            self._plc.ProcessorSlot = self.slot
            self._plc.Micro800 = True  # CRITICAL: Enables Micro800 CIP symbolic addressing
            self._plc.SocketTimeout = self.timeout

            # Test connection with a lightweight controller info query or test read
            # pylogix.GetDeviceProperties can query identity
            device = self._plc.GetDeviceProperties()
            if device and device.Status == "Success":
                logger.info(
                    "Connected to Allen-Bradley Device: %s (Rev %s)",
                    device.ProductName,
                    device.Revision,
                )
                self._connected = True
                return True
            else:
                status = getattr(device, "Status", "Unknown error")
                logger.warning("PLC handshake failed with status: %s", status)
                self._connected = False
                return False

        except Exception as exc:
            logger.error("Failed to connect to Micro850 @ %s: %s", self.ip, exc)
            self._connected = False
            return False

    def disconnect(self) -> None:
        """Close EtherNet/IP CIP socket."""
        if self._plc:
            try:
                self._plc.Close()
            except Exception as exc:
                logger.debug("Error while closing pylogix connection: %s", exc)
        self._connected = False
        logger.info("Live PLC connection closed.")

    def is_connected(self) -> bool:
        return self._connected

    def read_tags(self) -> Dict[str, Any]:
        """
        Read all configured global tags from Micro850.
        Returns a dictionary keyed by logical field names.
        """
        if not self._connected or not self._plc:
            raise ConnectionError(f"Micro850 @ {self.ip} is not connected. Call connect() first.")

        # Result dictionary initialized with timestamp
        results: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat()
        }

        try:
            # Batch read configured tags
            # pylogix Read() handles lists of tags and returns list of Response objects
            responses = self._plc.Read(self._tag_list)

            # If pylogix returned a single Response object instead of a list
            if not isinstance(responses, list):
                responses = [responses]

            for resp in responses:
                logical_name = self._plc_to_logical.get(resp.TagName)
                if not logical_name:
                    continue

                if resp.Status == "Success":
                    val = resp.Value
                    # Format / clean values
                    if isinstance(val, float):
                        val = round(val, 2)
                    results[logical_name] = val
                else:
                    logger.warning(
                        "Tag '%s' (PLC: '%s') read error: %s",
                        logical_name,
                        resp.TagName,
                        resp.Status,
                    )
                    # Provide safe default for missing tags
                    results[logical_name] = None

            # Verify that we got core telemetry; if all tags failed, PLC link might be down
            success_count = sum(1 for k, v in results.items() if k != "timestamp" and v is not None)
            if success_count == 0 and len(self._tag_list) > 0:
                self._connected = False
                raise ConnectionError(f"All tag reads failed on Micro850 @ {self.ip}. Connection assumed dropped.")

            return results

        except Exception as exc:
            self._connected = False
            logger.error("EtherNet/IP read exception on Micro850 @ %s: %s", self.ip, exc)
            raise ConnectionError(f"PLC communication failure: {exc}") from exc
