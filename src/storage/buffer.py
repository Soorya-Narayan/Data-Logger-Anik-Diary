"""
In-Memory Write Buffer.
Buffers 1-second telemetry samples in RAM to minimize SD card write-amplification.
Flushes to SQLite in batched atomic transactions.
"""

import time
import logging
import threading
from typing import List, Dict, Any

from src.storage.db import DatabaseManager

logger = logging.getLogger("DataBuffer")


class DataBuffer:
    """Thread-safe buffer holding telemetry samples before flushing to disk."""

    def __init__(self, db_manager: DatabaseManager, batch_flush_seconds: float = 15.0, batch_max_size: int = 30):
        self.db = db_manager
        self.batch_flush_seconds = batch_flush_seconds
        self.batch_max_size = batch_max_size

        self._buffer: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._last_flush_time = time.time()

    def add(self, record: Dict[str, Any]) -> None:
        """Add a new sample into the buffer and trigger flush if thresholds are reached."""
        with self._lock:
            self._buffer.append(record)
            should_flush = (
                len(self._buffer) >= self.batch_max_size
                or (time.time() - self._last_flush_time) >= self.batch_flush_seconds
            )

        if should_flush:
            self.flush()

    def flush(self) -> int:
        """Commit all pending records in the buffer to SQLite in a single transaction."""
        records_to_write = []
        with self._lock:
            if not self._buffer:
                return 0
            records_to_write = list(self._buffer)
            self._buffer.clear()
            self._last_flush_time = time.time()

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
