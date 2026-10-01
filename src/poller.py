"""
Main Data Acquisition Poller Service.
Polls 30 process telemetry instruments from the configured PLC (Mock or Live AB Micro850),
computes flow totalizer (Liters), Delta-T, failure states, and writes samples to SQLite.
"""

import os
import sys
import time
import json
import yaml
import signal
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.plc import get_plc_client
from src.storage import DatabaseManager, DataBuffer

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("PollerService")


class PollerApp:
    """Core daemon managing connection state, sampling interval, and graceful shutdown."""

    def __init__(self, config_path: str = "config/config.yaml", tags_path: str = "config/tags.json"):
        self.config_path = Path(config_path)
        self.tags_path = Path(tags_path)
        self.running = True
        self._totalizer_liters = 0.0
        self._last_sample_time = None

        self.load_configs()
        self.init_storage()
        self.init_plc()
        self.setup_signals()

    def load_configs(self):
        """Read YAML and JSON configuration files."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        with open(self.config_path, "r") as f:
            self.config = yaml.safe_load(f)

        if not self.tags_path.exists():
            raise FileNotFoundError(f"Tags mapping file not found: {self.tags_path}")
        with open(self.tags_path, "r") as f:
            self.tags_config = json.load(f)

    def init_storage(self):
        """Initialize SQLite database and write-behind buffer."""
        storage_cfg = self.config.get("storage", {})
        db_path = storage_cfg.get("db_path", "data/pasteurizer_data.db")
        batch_seconds = storage_cfg.get("batch_flush_seconds", 9.0)
        batch_size = storage_cfg.get("batch_max_size", 5)

        self.db = DatabaseManager(db_path=db_path)
        self.buffer = DataBuffer(
            db_manager=self.db,
            batch_flush_seconds=batch_seconds,
            batch_max_size=batch_size,
            async_mode=True
        )

        # Restore latest totalizer if available
        last_rec = self.db.get_latest_record()
        if last_rec and last_rec.get("product_tot"):
            self._totalizer_liters = float(last_rec.get("product_tot", 0.0))
            logger.info("Restored product totalizer: %.1f Liters", self._totalizer_liters)

        logger.info("Storage initialized with DB: %s (batch window: %ss / max: %d)", db_path, batch_seconds, batch_size)

    def init_plc(self):
        """Instantiate PLC driver based on config."""
        self.plc_client = get_plc_client(self.config, self.tags_config)

    def setup_signals(self):
        """Register graceful shutdown handlers for SIGINT (Ctrl+C) and SIGTERM (systemd stop)."""
        signal.signal(signal.SIGINT, self._handle_exit)
        signal.signal(signal.SIGTERM, self._handle_exit)

    def _handle_exit(self, signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info("Received signal %s. Initiating graceful shutdown...", sig_name)
        self.running = False

    def _enrich_telemetry(self, data: dict, now: float) -> dict:
        """Enrich raw PLC reads with calculated KPIs (Delta-T, Totalizer, Failures summary)."""
        # 1. Flow & Totalizer
        flow = data.get("feed_flow")
        if flow is None:
            flow = data.get("milk_flow", 0.0)
        else:
            data["milk_flow"] = flow

        if self._last_sample_time is not None:
            dt = max(0.0, now - self._last_sample_time)
            # Only accumulate if flow is positive
            if flow and flow > 10.0:
                self._totalizer_liters += (flow / 3600.0) * dt

        self._last_sample_time = now
        data["product_tot"] = round(self._totalizer_liters, 1)

        # 2. Complete 16-point Temperature Transmitter matrix (TT01 – TT16)
        # Fallback mappings for backward compatibility between old and new tags
        if "temp_product_in_tt01" in data and "temp_tt01" not in data:
            data["temp_tt01"] = data.get("temp_product_in_tt01")
        if "temp_tt01" in data and "temp_product_in_tt01" not in data:
            data["temp_product_in_tt01"] = data.get("temp_tt01")

        # TT13 and TT14 are physically not connected at the plant:
        # Sanitize open-circuit thermocouple floating values (e.g. -323°C)
        data["temp_tt13"] = None
        data["temp_tt14"] = None

        # Key pasteurizer process aliases:
        # TT05 = Holding Tube Inlet Temperature
        # TT06 = Holding Tube Outlet 1 Temperature (Legal Pasteurization Point)
        # TT08 = Holding Tube Outlet 2 Temperature (Verification)
        t_hold_in = data.get("temp_tt05")
        if t_hold_in is None:
            t_hold_in = data.get("temp_holding_in_tt04")  # Legacy fallback
        data["holding_in_temp"] = t_hold_in

        t_hold_out = data.get("temp_tt06")
        if t_hold_out is None:
            t_hold_out = data.get("temp_holding_out1_tt05")  # Legacy fallback
        data["holding_out_temp"] = t_hold_out

        # 3. Delta T calculation (Micro850 DIFFT6T1 = TEMP_6 - TEMP_1 = TT06 - TT01)
        raw_delta = data.get("delta_t")
        t_out1 = t_hold_out if t_hold_out is not None else 0.0
        t_in1 = data.get("temp_tt01") or 0.0
        if raw_delta is None or abs(float(raw_delta)) < 0.01:
            data["delta_t"] = round(abs(float(t_out1) - float(t_in1)), 2)
        else:
            data["delta_t"] = round(float(raw_delta), 2)

        # 4. Valve aliases
        if "hot_fdv_status" in data:
            data["fdv1_reason"] = data.get("hot_fdv_status")
        if "chill_fdv_status" in data:
            data["fdv2_reason"] = data.get("chill_fdv_status")
        data["fdv1_status"] = 1 if data.get("hot_fdv_open") else 0
        data["fdv2_status"] = 1 if data.get("chill_fdv_open") else 0

        # 5. Failures & Alarms compilation
        active_failures = []
        if data.get("alarm_main"):
            active_failures.append("MASTER ALARM")
        if data.get("alarm_fdv1"):
            active_failures.append("FDV1 DIVERT ALARM")
        if data.get("alarm_high_press1") or data.get("alarm_high_press2"):
            active_failures.append("HIGH PRESSURE")
        if data.get("trip_fdv1"):
            active_failures.append("FDV1 TRIP")
        if data.get("trip_fdv2"):
            active_failures.append("FDV2 TRIP")

        data["failures"] = ", ".join(active_failures) if active_failures else "NORMAL"

        return data

    def _publish_latest(self, data: Dict[str, Any]):
        """Publish latest sample to RAM tmpfs (/dev/shm or /tmp) for sub-millisecond dashboard reads."""
        try:
            shm_dir = Path("/dev/shm") if Path("/dev/shm").is_dir() else Path("/tmp")
            target = shm_dir / "pasteurizer_latest.json"
            tmp_target = shm_dir / "pasteurizer_latest.tmp"
            with open(tmp_target, "w") as f:
                json.dump(data, f)
            tmp_target.replace(target)
        except Exception as exc:
            logger.debug("Failed publishing live sample to RAM: %s", exc)

    def run(self):
        """Execution loop with automatic connection retries, drift-free 3.0s cadence, and async flushing."""
        poll_interval = float(self.config.get("polling", {}).get("interval_seconds", 3.0))
        plc_cfg = self.config.get("plc", {})
        retry_delay = plc_cfg.get("retry_initial_delay_sec", 1.0)
        retry_max = plc_cfg.get("retry_max_delay_sec", 30.0)
        backoff_mult = plc_cfg.get("retry_backoff_multiplier", 2.0)

        current_backoff = retry_delay

        logger.info("Starting Poller Service loop (target interval: %.2fs)", poll_interval)

        next_tick = time.monotonic()

        while self.running:
            # 1. Ensure PLC connection
            if not self.plc_client.is_connected():
                try:
                    logger.info("Connecting to PLC...")
                    connected = self.plc_client.connect()
                    if connected:
                        logger.info("PLC connected successfully.")
                        current_backoff = retry_delay
                        next_tick = time.monotonic()
                    else:
                        logger.warning("Connection attempt unsuccessful. Retrying in %.1fs...", current_backoff)
                        time.sleep(current_backoff)
                        current_backoff = min(current_backoff * backoff_mult, retry_max)
                        next_tick = time.monotonic()
                        continue
                except Exception as exc:
                    logger.error("PLC connection exception: %s. Retrying in %.1fs...", exc, current_backoff)
                    time.sleep(current_backoff)
                    current_backoff = min(current_backoff * backoff_mult, retry_max)
                    next_tick = time.monotonic()
                    continue

            # 2. Sample telemetry
            loop_start = time.time()
            try:
                data = self.plc_client.read_tags()
                data = self._enrich_telemetry(data, loop_start)
                self.buffer.add(data)
                self._publish_latest(data)
                current_backoff = retry_delay

            except ConnectionError as ce:
                logger.warning("PLC communication lost: %s. Entering reconnect loop...", ce)
                self.plc_client.disconnect()
                time.sleep(current_backoff)
                current_backoff = min(current_backoff * backoff_mult, retry_max)
                next_tick = time.monotonic()
                continue
            except Exception as exc:
                logger.error("Unexpected error during polling cycle: %s", exc, exc_info=True)

            # 3. Maintain consistent 3.0s cadence with monotonic drift compensation
            next_tick += poll_interval
            now_mono = time.monotonic()
            if next_tick < now_mono:
                # Catch up if delayed by heavy network interruption
                next_tick = now_mono + poll_interval
            sleep_time = max(0.0, next_tick - now_mono)
            time.sleep(sleep_time)

        # Cleanup on exit
        logger.info("Flushing pending buffer records to disk...")
        self.buffer.close()
        self.plc_client.disconnect()
        logger.info("Poller Service terminated cleanly.")


if __name__ == "__main__":
    app = PollerApp()
    app.run()
