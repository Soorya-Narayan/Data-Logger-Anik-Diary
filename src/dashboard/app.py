"""
Flask Web Dashboard for 10 KL Pasteurizer Data Logger.
Provides real-time process monitoring, tag views, and trend charts for LAN client PCs.
"""

import os
import sys
import yaml
import json
import psutil
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, jsonify, request

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.storage import DatabaseManager

app = Flask(__name__)

# Load config
CONFIG_PATH = Path("config/config.yaml")
TAGS_PATH = Path("config/tags.json")

def load_yaml(path: Path) -> dict:
    if path.exists():
        with open(path, "r") as f:
            return yaml.safe_load(f)
    return {}

config = load_yaml(CONFIG_PATH)
db_path = config.get("storage", {}).get("db_path", "data/pasteurizer_data.db")
db = DatabaseManager(db_path=db_path)


@app.route("/")
def index():
    """Main dashboard interface."""
    plant_info = config.get("plant", {})
    plc_mode = config.get("plc", {}).get("mode", "mock").upper()
    plc_ip = config.get("plc", {}).get("ip", "192.168.1.50")
    poll_interval = config.get("dashboard", {}).get("client_poll_interval_ms", 1000)

    return render_template(
        "index.html",
        plant_name=plant_info.get("name", "Anik Dairy - Bhopal"),
        unit_name=plant_info.get("unit", "10 KL Pasteurizer"),
        reference_line=plant_info.get("reference_line", "PHE-3"),
        plc_mode=plc_mode,
        plc_ip=plc_ip,
        poll_interval=poll_interval
    )


@app.route("/api/current")
def api_current():
    """Returns the single latest recorded sample."""
    record = db.get_latest_record()
    if not record:
        return jsonify({
            "status": "waiting",
            "message": "No telemetry recorded yet in database.",
            "data": None
        })

    return jsonify({
        "status": "ok",
        "data": record
    })


@app.route("/api/history")
def api_history():
    """
    Returns time series data for live Chart.js trend.
    Query param 'minutes' specifies window (default 30 min).
    """
    minutes = request.args.get("minutes", default=30, type=int)
    minutes = max(1, min(180, minutes))  # Limit between 1 and 180 min

    start_time = datetime.now() - timedelta(minutes=minutes)
    start_iso = start_time.isoformat()
    end_iso = datetime.now().isoformat()

    rows = db.get_records_between(start_iso, end_iso)

    # If rows > 600 points, downsample dynamically for browser performance
    total = len(rows)
    step = 1
    if total > 600:
        step = total // 600

    sampled = rows[::step] if step > 1 else rows

    return jsonify({
        "status": "ok",
        "count": len(sampled),
        "total_records": total,
        "data": sampled
    })


@app.route("/api/system")
def api_system():
    """Raspberry Pi system health indicators (memory, CPU, disk, thermal)."""
    cpu_usage = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    # Read Raspberry Pi CPU temperature if available
    cpu_temp = None
    thermal_file = Path("/sys/class/thermal/thermal_zone0/temp")
    if thermal_file.exists():
        try:
            with open(thermal_file, "r") as f:
                cpu_temp = round(int(f.read().strip()) / 1000.0, 1)
        except Exception:
            pass

    return jsonify({
        "cpu_usage_pct": cpu_usage,
        "cpu_temp_c": cpu_temp,
        "memory_used_mb": round(mem.used / (1024 * 1024), 1),
        "memory_total_mb": round(mem.total / (1024 * 1024), 1),
        "disk_free_gb": round(disk.free / (1024 * 1024 * 1024), 2),
        "disk_total_gb": round(disk.total / (1024 * 1024 * 1024), 2),
        "disk_used_pct": disk.percent
    })


if __name__ == "__main__":
    dash_cfg = config.get("dashboard", {})
    host = dash_cfg.get("host", "0.0.0.0")
    port = dash_cfg.get("port", 8080)
    app.run(host=host, port=port, debug=False)
