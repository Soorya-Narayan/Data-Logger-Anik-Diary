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
        batch_seconds = storage_cfg.get("batch_flush_seconds", 15.0)
        batch_size = storage_cfg.get("batch_max_size", 30)

        self.db = DatabaseManager(db_path=db_path)
        self.buffer = DataBuffer(
            db_manager=self.db,
            batch_flush_seconds=batch_seconds,
            batch_max_size=batch_size
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

        # 2. Backwards-compatibility aliases for legacy templates & charts
        if "temp_product_in_tt01" in data and "holding_in_temp" not in data:
            data["holding_in_temp"] = data.get("temp_product_in_tt01")
        if "temp_chilling_tt08" in data and "holding_out_temp" not in data:
            data["holding_out_temp"] = data.get("temp_chilling_tt08")

        # 3. Delta T calculation
        raw_delta = data.get("delta_t")
        t_out1 = data.get("temp_holding_out1_tt05") or 0.0
        t_in = data.get("temp_product_in_tt01") or 0.0
        if raw_delta is None or abs(float(raw_delta)) < 0.01:
            data["delta_t"] = round(abs(float(t_out1) - float(t_in)), 2)
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

    def run(self):
        """Execution loop with automatic connection retries and exponential backoff."""
        poll_interval = self.config.get("polling", {}).get("interval_seconds", 1.0)
        plc_cfg = self.config.get("plc", {})
        retry_delay = plc_cfg.get("retry_initial_delay_sec", 1.0)
        retry_max = plc_cfg.get("retry_max_delay_sec", 30.0)
        backoff_mult = plc_cfg.get("retry_backoff_multiplier", 2.0)

        current_backoff = retry_delay

        logger.info("Starting Poller Service loop (target interval: %.2fs)", poll_interval)

        while self.running:
            # 1. Ensure PLC connection
            if not self.plc_client.is_connected():
                try:
                    logger.info("Connecting to PLC...")
                    connected = self.plc_client.connect()
                    if connected:
                        logger.info("PLC connected successfully.")
                        current_backoff = retry_delay
                    else:
                        logger.warning("Connection attempt unsuccessful. Retrying in %.1fs...", current_backoff)
                        time.sleep(current_backoff)
                        current_backoff = min(current_backoff * backoff_mult, retry_max)
                        continue
                except Exception as exc:
                    logger.error("PLC connection exception: %s. Retrying in %.1fs...", exc, current_backoff)
                    time.sleep(current_backoff)
                    current_backoff = min(current_backoff * backoff_mult, retry_max)
                    continue

            # 2. Sample telemetry
            loop_start = time.time()
            try:
                data = self.plc_client.read_tags()
                data = self._enrich_telemetry(data, loop_start)
                self.buffer.add(data)
                current_backoff = retry_delay

            except ConnectionError as ce:
                logger.warning("PLC communication lost: %s. Entering reconnect loop...", ce)
                self.plc_client.disconnect()
                time.sleep(current_backoff)
                current_backoff = min(current_backoff * backoff_mult, retry_max)
                continue
            except Exception as exc:
                logger.error("Unexpected error during polling cycle: %s", exc, exc_info=True)

            # 3. Maintain consistent sampling period
            elapsed = time.time() - loop_start
            sleep_time = max(0.0, poll_interval - elapsed)
            time.sleep(sleep_time)

        # Cleanup on exit
        logger.info("Flushing pending buffer records to disk...")
        flushed = self.buffer.flush()
        logger.info("Flushed %d remaining records.", flushed)
        self.plc_client.disconnect()
        logger.info("Poller Service terminated cleanly.")


if __name__ == "__main__":
    app = PollerApp()
    app.run()
