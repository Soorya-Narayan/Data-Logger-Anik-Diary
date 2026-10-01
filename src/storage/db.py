"""
SQLite Database Storage Manager.
Optimized for Raspberry Pi SD card longevity using WAL mode and PRAGMA tunings.
Supports all 30 Pasteurizer SCADA instruments with automated backward-compatible migrations.
"""

import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("DatabaseManager")


# Complete list of dynamic columns added to pasteurizer_logs
NEW_COLUMNS = [
    ("feed_flow", "REAL"),
    ("product_tot", "REAL"),
    ("temp_product_in_tt01", "REAL"),
    ("temp_regen_r2_tt03", "REAL"),
    ("temp_holding_in_tt04", "REAL"),
    ("temp_holding_out1_tt05", "REAL"),
    ("temp_holding_out2_tt06", "REAL"),
    ("temp_chilled_milk_tt07", "REAL"),
    ("temp_chilling_tt08", "REAL"),
    ("temp_hot_water_tt09", "REAL"),
    # Complete 16-point Temperature Transmitter matrix (TT01 – TT16)
    ("temp_tt01", "REAL"),
    ("temp_tt02", "REAL"),
    ("temp_tt03", "REAL"),
    ("temp_tt04", "REAL"),
    ("temp_tt05", "REAL"),
    ("temp_tt06", "REAL"),
    ("temp_tt07", "REAL"),
    ("temp_tt08", "REAL"),
    ("temp_tt09", "REAL"),
    ("temp_tt10", "REAL"),
    ("temp_tt11", "REAL"),
    ("temp_tt12", "REAL"),
    ("temp_tt13", "REAL"),
    ("temp_tt14", "REAL"),
    ("temp_tt15", "REAL"),
    ("temp_tt16", "REAL"),
    ("delta_t", "REAL"),
    ("press_raw_milk_pt01", "REAL"),
    ("press_regen_r2_pt02", "REAL"),
    ("press_holding_in_pt03", "REAL"),
    ("press_chilled_milk_pt04", "REAL"),
    ("press_hot_water_pt05", "REAL"),
    ("press_chilling_pt06", "REAL"),
    ("steam_cv", "REAL"),
    ("deodoriser_level", "REAL"),
    ("regen_efficiency", "REAL"),
    ("sp_heating_temp", "REAL"),
    ("sp_chill_fdv_diversion", "REAL"),
    ("sp_heating_fdv_hys", "REAL"),
    ("sp_chilling_pressure", "REAL"),
    ("sp_regen_r1_pressure", "REAL"),
    ("hot_fdv_status", "TEXT"),
    ("hot_fdv_open", "INTEGER"),
    ("chill_fdv_status", "TEXT"),
    ("chill_fdv_open", "INTEGER"),
    ("force_circulation", "INTEGER"),
    ("force_forward", "INTEGER"),
    ("failures", "TEXT"),
    ("alarm_main", "INTEGER"),
    ("alarm_fdv1", "INTEGER"),
    ("alarm_high_press1", "INTEGER"),
    ("alarm_high_press2", "INTEGER"),
    ("trip_fdv1", "INTEGER"),
    ("trip_fdv2", "INTEGER"),
]

BASE_SCHEMA_SQL = """
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
    """Manages SQLite connection, schema creation, automated migrations, and optimized batch insertions."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
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
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA cache_size = -64000;")  # 64MB cache in RAM
        conn.execute("PRAGMA temp_store = MEMORY;")
        return conn

    def _init_db(self):
        """Create schema and apply backward-compatible column migrations."""
        conn = self._get_connection()
        try:
            conn.executescript(BASE_SCHEMA_SQL)
            self._migrate_schema(conn)
            logger.info("Database initialized & migrated successfully at %s", self.db_path)
        except Exception as exc:
            logger.error("Failed to initialize database: %s", exc)
            raise
        finally:
            conn.close()

    def _migrate_schema(self, conn: sqlite3.Connection):
        """Ensures all 30 instrument columns exist in pasteurizer_logs table."""
        cursor = conn.execute("PRAGMA table_info(pasteurizer_logs);")
        existing_cols = {row["name"] for row in cursor.fetchall()}

        for col_name, col_type in NEW_COLUMNS:
            if col_name not in existing_cols:
                try:
                    conn.execute(f"ALTER TABLE pasteurizer_logs ADD COLUMN {col_name} {col_type};")
                    logger.info("Added missing column '%s' (%s) to pasteurizer_logs", col_name, col_type)
                except sqlite3.OperationalError as err:
                    logger.debug("Column migration skipped for %s: %s", col_name, err)

    def insert_batch(self, records: List[Dict[str, Any]]) -> int:
        """Atomically insert a batch of telemetry records with all 30 instruments."""
        if not records:
            return 0

        # Build dynamic insert columns based on available fields
        conn = self._get_connection()
        try:
            cursor = conn.execute("PRAGMA table_info(pasteurizer_logs);")
            valid_cols = [row["name"] for row in cursor.fetchall() if row["name"] != "id"]

            col_names_str = ", ".join(valid_cols)
            placeholders_str = ", ".join(f":{c}" for c in valid_cols)
            insert_sql = f"INSERT INTO pasteurizer_logs ({col_names_str}) VALUES ({placeholders_str});"

            clean_records = []
            for r in records:
                row_dict = {}
                for c in valid_cols:
                    val = r.get(c)
                    # Convert booleans to integer for SQLite
                    if isinstance(val, bool):
                        val = 1 if val else 0
                    elif isinstance(val, (dict, list)):
                        import json
                        val = json.dumps(val)
                    row_dict[c] = val
                clean_records.append(row_dict)

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
        """Retrieve latest N records in chronological order."""
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
