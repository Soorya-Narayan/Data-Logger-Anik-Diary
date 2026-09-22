"""
SQLite Database Storage Manager.
Optimized for Raspberry Pi SD card longevity using WAL mode and PRAGMA tunings.
"""

import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("DatabaseManager")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pasteurizer_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    milk_flow REAL,
    holding_in_temp REAL,
    holding_out_temp REAL,
    product TEXT,
    status TEXT,
    fdv1_status INTEGER,
    fdv1_reason TEXT,
    fdv2_status INTEGER,
    fdv2_reason TEXT,
    cip_status INTEGER,
    cip_step TEXT,
    fdv_feedback INTEGER
);

CREATE INDEX IF NOT EXISTS idx_pasteurizer_timestamp ON pasteurizer_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_pasteurizer_product ON pasteurizer_logs(product);
CREATE INDEX IF NOT EXISTS idx_pasteurizer_cip ON pasteurizer_logs(cip_status);
"""


class DatabaseManager:
    """Manages SQLite connection, schema creation, and optimized batch insertions."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        # Ensure parent directories exist
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a configured SQLite connection with WAL mode and row factory."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=15.0,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        # Crucial SD card wear reduction pragmas
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA cache_size = -64000;")  # 64MB cache in RAM
        conn.execute("PRAGMA temp_store = MEMORY;")
        return conn

    def _init_db(self):
        """Create schema and indexes if they do not exist."""
        conn = self._get_connection()
        try:
            conn.executescript(SCHEMA_SQL)
            logger.info("Database initialized successfully at %s (WAL mode enabled)", self.db_path)
        except Exception as exc:
            logger.error("Failed to initialize database: %s", exc)
            raise
        finally:
            conn.close()

    def insert_batch(self, records: List[Dict[str, Any]]) -> int:
        """
        Atomically insert a batch of telemetry records in a single transaction.
        Significantly reduces SD card writes compared to row-by-row commits.
        """
        if not records:
            return 0

        insert_sql = """
        INSERT INTO pasteurizer_logs (
            timestamp, milk_flow, holding_in_temp, holding_out_temp,
            product, status, fdv1_status, fdv1_reason,
            fdv2_status, fdv2_reason, cip_status, cip_step, fdv_feedback
        ) VALUES (
            :timestamp, :milk_flow, :holding_in_temp, :holding_out_temp,
            :product, :status, :fdv1_status, :fdv1_reason,
            :fdv2_status, :fdv2_reason, :cip_status, :cip_step, :fdv_feedback
        );
        """

        clean_records = []
        for r in records:
            clean_records.append({
                "timestamp": r.get("timestamp"),
                "milk_flow": r.get("milk_flow"),
                "holding_in_temp": r.get("holding_in_temp"),
                "holding_out_temp": r.get("holding_out_temp"),
                "product": r.get("product"),
                "status": r.get("status"),
                "fdv1_status": r.get("fdv1_status"),
                "fdv1_reason": r.get("fdv1_reason"),
                "fdv2_status": r.get("fdv2_status"),
                "fdv2_reason": r.get("fdv2_reason"),
                "cip_status": r.get("cip_status"),
                "cip_step": r.get("cip_step"),
                "fdv_feedback": r.get("fdv_feedback"),
            })

        conn = self._get_connection()
        try:
            with conn:
                conn.executemany(insert_sql, clean_records)
            return len(clean_records)
        finally:
            conn.close()

    def get_latest_record(self) -> Optional[Dict[str, Any]]:
        """Retrieve the most recent logged record."""
        sql = "SELECT * FROM pasteurizer_logs ORDER BY id DESC LIMIT 1;"
        conn = self._get_connection()
        try:
            cursor = conn.execute(sql)
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            conn.close()

    def get_recent_records(self, limit: int = 1800) -> List[Dict[str, Any]]:
        """
        Retrieve latest N records in chronological order.
        1800 records = 30 minutes at 1-sec resolution.
        """
        sql = """
        SELECT * FROM (
            SELECT * FROM pasteurizer_logs ORDER BY id DESC LIMIT ?
        ) ORDER BY id ASC;
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(sql, (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_records_between(self, start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
        """Query records across a specified time range for reports."""
        sql = """
        SELECT * FROM pasteurizer_logs
        WHERE timestamp >= ? AND timestamp <= ?
        ORDER BY timestamp ASC;
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(sql, (start_iso, end_iso))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
