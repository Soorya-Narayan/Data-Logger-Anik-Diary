"""
Main Data Acquisition Poller Service.
Polls process telemetry from the configured PLC (Mock or Live AB Micro850)
and writes samples to SQLite via an SD-card optimized in-memory buffer.
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
                        current_backoff = retry_delay  # Reset backoff on success
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
                self.buffer.add(data)
                # Reset backoff on successful sample
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
