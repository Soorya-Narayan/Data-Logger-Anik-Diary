"""
In-Memory Write Buffer.
Buffers telemetry samples in RAM to minimize SD card write-amplification.
Supports asynchronous background flushing to ensure the poller data acquisition loop
is never delayed or blocked during database disk commits or concurrent report exports.
"""

import time
import logging
import threading
from typing import List, Dict, Any, Optional

from src.storage.db import DatabaseManager

logger = logging.getLogger("DataBuffer")


class DataBuffer:
    """Thread-safe write-behind buffer holding telemetry samples before flushing to disk.

    In async_mode (recommended for poller daemon), a background worker thread handles
    SQLite batch insertions, completely decoupling the 3-second sampling loop from disk I/O.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        batch_flush_seconds: float = 9.0,
        batch_max_size: int = 5,
        async_mode: bool = False
    ):
        self.db = db_manager
        self.batch_flush_seconds = batch_flush_seconds
        self.batch_max_size = batch_max_size
        self.async_mode = async_mode

        self._buffer: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._last_flush_time = time.monotonic()

        self._stop_event = threading.Event()
        self._flush_event = threading.Event()
        self._worker: Optional[threading.Thread] = None

        if self.async_mode:
            self._worker = threading.Thread(target=self._worker_loop, name="DataBufferWorker", daemon=True)
            self._worker.start()
            logger.info(
                "DataBuffer initialized in asynchronous write-behind mode (window: %.1fs, max_size: %d)",
                batch_flush_seconds,
                batch_max_size
            )

    def _worker_loop(self):
        """Dedicated background thread handling SQLite disk transactions without stalling acquisition."""
        while not self._stop_event.is_set():
            # Wait until batch_flush_seconds timeout OR signaled by add()
            self._flush_event.wait(timeout=self.batch_flush_seconds)
            self._flush_event.clear()
            self._flush_internal()

        # Final drain on termination
        self._flush_internal()

    def add(self, record: Dict[str, Any]) -> None:
        """Add a new sample into the buffer and trigger flush if thresholds are reached.

        In async_mode, this method returns in microseconds without waiting for disk I/O.
        """
        with self._lock:
            self._buffer.append(record)
            now = time.monotonic()
            should_flush = (
                len(self._buffer) >= self.batch_max_size
                or (now - self._last_flush_time) >= self.batch_flush_seconds
            )

        if should_flush:
            if self.async_mode:
                self._flush_event.set()
            else:
                self.flush()

    def flush(self) -> int:
        """Commit all pending records in the buffer to SQLite in a single transaction."""
        return self._flush_internal()

    def _flush_internal(self) -> int:
        records_to_write = []
        with self._lock:
            if not self._buffer:
                return 0
            records_to_write = list(self._buffer)
            self._buffer.clear()
            self._last_flush_time = time.monotonic()

        count = len(records_to_write)
        try:
            inserted = self.db.insert_batch(records_to_write)
            logger.debug("Flushed %d telemetry records to SQLite database", inserted)
            return inserted
        except Exception as exc:
            logger.error("Failed to flush batch of %d records to database: %s", count, exc)
            # Re-queue failed records back into buffer to avoid data loss
            with self._lock:
                self._buffer = records_to_write + self._buffer
            return 0

    def pending_count(self) -> int:
        """Number of records currently waiting in the memory buffer."""
        with self._lock:
            return len(self._buffer)

    def close(self):
        """Stop background worker and flush remaining records cleanly."""
        if self.async_mode and self._worker:
            self._stop_event.set()
            self._flush_event.set()
            self._worker.join(timeout=5.0)
        self.flush()
