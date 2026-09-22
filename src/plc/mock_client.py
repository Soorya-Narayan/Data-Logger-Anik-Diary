"""
Mock PLC Client simulating the 10 KL Pasteurizer at Anik Dairy (Bhopal).
Emulates real SCADA process behavior based on the sister-line PHE-3 reference dataset.
"""

import time
import random
import logging
from datetime import datetime
from typing import Dict, Any

from src.plc.base import BasePLCClient

logger = logging.getLogger("MockPLCClient")


class MockPLCClient(BasePLCClient):
    """
    Simulates pasteurizer operation including:
    - Production Accepted (~33,000 L/hr, 81°C, FDVs Forward)
    - Temperature dip and FDV Divert events
    - Production Circulation (Recirculation at balance tank)
    - CIP Cycle (Caustic 88-92°C, Acid 72°C, Sanitisation 92°C, Final Flush 55°C)
    - Simulated connection dropouts to test polling retry logic
    """

    STATES = [
        "PRODUCTION_ACCEPTED",
        "DIVERSION_EVENT",
        "PRODUCTION_CIRCULATION",
        "CIP_CAUSTIC",
        "CIP_INTERMEDIATE_FLUSH",
        "CIP_ACID",
        "CIP_SANITISATION",
        "CIP_FINAL_FLUSH",
        "IDLE",
    ]

    PRODUCTS = ["TONED_MILK_RUN_01", "STANDARDIZED_MILK_RUN_02"]

    def __init__(self, config: dict):
        self.config = config
        mock_cfg = config.get("plc", {}).get("mock", {})
        self.enable_dropouts = mock_cfg.get("enable_random_dropouts", True)
        self.dropout_prob = mock_cfg.get("dropout_probability", 0.005)
        self.dropout_duration = mock_cfg.get("dropout_duration_cycles", 3)

        self._connected = False
        self._dropout_counter = 0

        # State tracking
        self._state = "PRODUCTION_ACCEPTED"
        self._state_ticks = 0
        self._product_idx = 0
        self._step_counter = 0

        # Physical telemetry initial values
        self._flow = 33200.0  # L/hr
        self._holding_in_temp = 81.2  # °C
        self._holding_out_temp = 80.9  # °C

    def connect(self) -> bool:
        """Simulate connecting to Allen Bradley PLC."""
        time.sleep(0.05)  # Simulate small socket handshake
        self._connected = True
        logger.info("MockPLCClient connected (simulating AB Micro850 @ %s)", self.config.get("plc", {}).get("ip", "192.168.1.50"))
        return True

    def disconnect(self) -> None:
        """Simulate disconnecting."""
        self._connected = False
        logger.info("MockPLCClient disconnected")

    def is_connected(self) -> bool:
        return self._connected

    def _maybe_simulate_dropout(self):
        """Simulate random communication glitch / Ethernet drop."""
        if self._dropout_counter > 0:
            self._dropout_counter -= 1
            if self._dropout_counter == 0:
                logger.info("Mock connection dropout recovered")
            else:
                raise ConnectionError("Simulated EtherNet/IP socket timeout (Micro850 unreachable)")

        if self.enable_dropouts and random.random() < self.dropout_prob:
            self._dropout_counter = self.dropout_duration
            logger.warning("Simulating transient network dropout on Micro850 EtherNet/IP link")
            raise ConnectionError("Simulated EtherNet/IP socket timeout (Micro850 unreachable)")

    def _update_state_machine(self):
        """Advance the simulated pasteurizer operational phases."""
        self._state_ticks += 1

        # Phase duration logic (in polling ticks / seconds)
        # Production runs for ~120s in mock mode (can be scaled), then occasional diversion or CIP
        if self._state == "PRODUCTION_ACCEPTED":
            if self._state_ticks > 90 and random.random() < 0.08:
                # Brief temperature dip triggering safety diversion
                self._state = "DIVERSION_EVENT"
                self._state_ticks = 0
            elif self._state_ticks > 250:
                # Production run complete, enter CIP sequence
                self._state = "CIP_CAUSTIC"
                self._state_ticks = 0
                self._product_idx = (self._product_idx + 1) % len(self.PRODUCTS)

        elif self._state == "DIVERSION_EVENT":
            if self._state_ticks > 15:  # Divert for ~15 seconds then recover
                self._state = "PRODUCTION_ACCEPTED"
                self._state_ticks = 0

        elif self._state == "CIP_CAUSTIC":
            if self._state_ticks > 40:
                self._state = "CIP_INTERMEDIATE_FLUSH"
                self._state_ticks = 0

        elif self._state == "CIP_INTERMEDIATE_FLUSH":
            if self._state_ticks > 20:
                self._state = "CIP_ACID"
                self._state_ticks = 0

        elif self._state == "CIP_ACID":
            if self._state_ticks > 30:
                self._state = "CIP_SANITISATION"
                self._state_ticks = 0

        elif self._state == "CIP_SANITISATION":
            if self._state_ticks > 30:
                self._state = "CIP_FINAL_FLUSH"
                self._state_ticks = 0

        elif self._state == "CIP_FINAL_FLUSH":
            if self._state_ticks > 20:
                self._state = "PRODUCTION_CIRCULATION"
                self._state_ticks = 0

        elif self._state == "PRODUCTION_CIRCULATION":
            if self._state_ticks > 25:
                # Circulation brought temp to setpoint, forward production accepted
                self._state = "PRODUCTION_ACCEPTED"
                self._state_ticks = 0

    def read_tags(self) -> Dict[str, Any]:
        """Generate realistic 1-second telemetry matching the PHE-3 SCADA report."""
        if not self._connected:
            raise ConnectionError("MockPLCClient is not connected. Call connect() first.")

        self._maybe_simulate_dropout()
        self._update_state_machine()

        now_iso = datetime.now().isoformat()
        current_product = self.PRODUCTS[self._product_idx]

        # 1. Physical parameter emulation based on active phase
        if self._state == "PRODUCTION_ACCEPTED":
            # Flow fluctuates realistically between 30,000 and 36,000 L/hr
            self._flow += random.uniform(-150.0, 150.0)
            self._flow = max(29500.0, min(36500.0, self._flow))

            # Holding temperature steady around 81.2°C
            self._holding_in_temp = 81.2 + random.gauss(0, 0.15)
            self._holding_out_temp = self._holding_in_temp - 0.35 + random.gauss(0, 0.08)

            status_str = "PRODUCTION ACCEPTED: FDV-1 Forward & FDV-2 Forward"
            fdv1_status = 1
            fdv1_reason = "All Ok"
            fdv2_status = 1
            fdv2_reason = "All Ok"
            cip_status = 0
            cip_step = "None"
            fdv_feedback = 3  # Binary 11 = both forward switches engaged

        elif self._state == "DIVERSION_EVENT":
            # Flow temporarily routed to balance tank; pump remains running
            self._flow += random.uniform(-200.0, 200.0)
            self._flow = max(28000.0, min(34000.0, self._flow))

            # Temperature dipped below 78.5°C threshold
            self._holding_in_temp = 77.8 + random.gauss(0, 0.2)
            self._holding_out_temp = self._holding_in_temp - 0.4

            status_str = "PRODUCTION CIRCULATION: FDV-1 Divert & FDV-2 Divert (Sub-cooling)"
            fdv1_status = 0
            fdv1_reason = "Holding Temp < 78.5 C"
            fdv2_status = 0
            fdv2_reason = "Holding Temp < 78.5 C"
            cip_status = 0
            cip_step = "None"
            fdv_feedback = 0  # Binary 00 = both diverted

        elif self._state == "PRODUCTION_CIRCULATION":
            self._flow = 0.0  # Or water circulation
            self._holding_in_temp = 79.5 + random.gauss(0, 0.3)
            self._holding_out_temp = self._holding_in_temp - 0.5
            status_str = "PRODUCTION CIRCULATION: FDV-1 Divert & FDV-2 Divert"
            fdv1_status = 0
            fdv1_reason = "Pre-heat recirculation"
            fdv2_status = 0
            fdv2_reason = "Pre-heat recirculation"
            cip_status = 0
            cip_step = "Pre-Production Loop"
            fdv_feedback = 0

        elif self._state == "CIP_CAUSTIC":
            self._flow = 0.0  # Flowmeter is for milk line; CIP measured separately or 0
            self._holding_in_temp = 89.5 + random.gauss(0, 0.4)  # 87 - 92 C
            self._holding_out_temp = self._holding_in_temp - 0.6
            status_str = "CIP: Caustic Flush running"
            fdv1_status = 1
            fdv1_reason = "CIP Forward Cycle"
            fdv2_status = 1
            fdv2_reason = "CIP Forward Cycle"
            cip_status = 1
            cip_step = "Hot Caustic Circulation (2.0%)"
            fdv_feedback = 3

        elif self._state == "CIP_INTERMEDIATE_FLUSH":
            self._flow = 0.0
            self._holding_in_temp = 58.0 + random.gauss(0, 0.5)
            self._holding_out_temp = self._holding_in_temp - 0.5
            status_str = "CIP: Intermediate Water Flush running"
            fdv1_status = 1
            fdv1_reason = "CIP Forward Cycle"
            fdv2_status = 1
            fdv2_reason = "CIP Forward Cycle"
            cip_status = 1
            cip_step = "Intermediate RO Rinse"
            fdv_feedback = 3

        elif self._state == "CIP_ACID":
            self._flow = 0.0
            self._holding_in_temp = 72.0 + random.gauss(0, 0.3)  # ~72 C
            self._holding_out_temp = self._holding_in_temp - 0.4
            status_str = "CIP: Acid Flush running"
            fdv1_status = 1
            fdv1_reason = "CIP Forward Cycle"
            fdv2_status = 1
            fdv2_reason = "CIP Forward Cycle"
            cip_status = 1
            cip_step = "Nitric Acid Circulation (1.0%)"
            fdv_feedback = 3

        elif self._state == "CIP_SANITISATION":
            self._flow = 0.0
            self._holding_in_temp = 93.0 + random.gauss(0, 0.4)  # High temp sanitisation 90-95 C
            self._holding_out_temp = self._holding_in_temp - 0.5
            status_str = "CIP: Final Sanitisation running"
            fdv1_status = 1
            fdv1_reason = "CIP Forward Cycle"
            fdv2_status = 1
            fdv2_reason = "CIP Forward Cycle"
            cip_status = 1
            cip_step = "Hot Water Disinfection"
            fdv_feedback = 3

        elif self._state == "CIP_FINAL_FLUSH":
            self._flow = 0.0
            self._holding_in_temp = 52.0 + random.gauss(0, 0.5)
            self._holding_out_temp = self._holding_in_temp - 0.4
            status_str = "CIP: Final Water Flush running"
            fdv1_status = 1
            fdv1_reason = "CIP Forward Cycle"
            fdv2_status = 1
            fdv2_reason = "CIP Forward Cycle"
            cip_status = 1
            cip_step = "Treated Cold Water Rinse"
            fdv_feedback = 3

        else:  # IDLE
            self._flow = 0.0
            self._holding_in_temp = 42.0 + random.gauss(0, 0.5)
            self._holding_out_temp = self._holding_in_temp - 0.3
            status_str = "IDLE: Pasteurizer Standby"
            fdv1_status = 0
            fdv1_reason = "System Idle"
            fdv2_status = 0
            fdv2_reason = "System Idle"
            cip_status = 0
            cip_step = "Idle"
            fdv_feedback = 0

        return {
            "timestamp": now_iso,
            "milk_flow": round(self._flow, 1),
            "holding_in_temp": round(self._holding_in_temp, 2),
            "holding_out_temp": round(self._holding_out_temp, 2),
            "product": current_product,
            "status": status_str,
            "fdv1_status": fdv1_status,
            "fdv1_reason": fdv1_reason,
            "fdv2_status": fdv2_status,
            "fdv2_reason": fdv2_reason,
            "cip_status": cip_status,
            "cip_step": cip_step,
            "fdv_feedback": fdv_feedback,
        }
