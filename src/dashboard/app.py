"""
Flask Web Dashboard for 10 KL Pasteurizer Data Logger.
Provides real-time process monitoring, tag views, and trend charts for LAN client PCs.
"""

import os
import sys
import yaml
import json
try:
    import psutil
except ImportError:
    psutil = None

from datetime import datetime, timedelta
from pathlib import Path
import csv
import io
from flask import Flask, render_template, jsonify, request, send_file, Response

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.storage import DatabaseManager

app = Flask(__name__)

# Load config
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config/config.yaml"
TAGS_PATH = PROJECT_ROOT / "config/tags.json"
REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

def load_yaml(path: Path) -> dict:
    if path.exists():
        with open(path, "r") as f:
            return yaml.safe_load(f)
    return {}

config = load_yaml(CONFIG_PATH)
db_path = config.get("storage", {}).get("db_path", "data/pasteurizer_data.db")
if not Path(db_path).is_absolute():
    db_path = str(PROJECT_ROOT / db_path)

db = DatabaseManager(db_path=db_path)

excel_gen = None
pdf_gen = None
try:
    from src.reports.generator import ExcelReportGenerator
    excel_gen = ExcelReportGenerator(db_manager=db, output_dir=str(REPORTS_DIR), plant_info=config.get("plant"))
except ImportError as err:
    print(f"[Warning] Excel generator not loaded ({err}). Install pandas and openpyxl.")

try:
    from src.reports.pdf_generator import PDFReportGenerator
    pdf_gen = PDFReportGenerator(db_manager=db, output_dir=str(REPORTS_DIR), plant_info=config.get("plant"))
except ImportError as err:
    print(f"[Warning] PDF generator not loaded ({err}). Install reportlab and pillow.")


APP_VERSION = "v3.4.0"


@app.route("/")
def index():
    """Main dashboard interface."""
    plant_info = config.get("plant", {})
    plc_mode = config.get("plc", {}).get("mode", "mock").upper()
    plc_ip = config.get("plc", {}).get("ip", "192.168.1.50")
    poll_interval = config.get("dashboard", {}).get("client_poll_interval_ms", 3000)

    return render_template(
        "index.html",
        plant_name=plant_info.get("name", "Anik Dairy - Bhopal"),
        unit_name=plant_info.get("unit", "10 KL Pasteurizer"),
        reference_line=plant_info.get("reference_line", "PHE-3"),
        plc_mode=plc_mode,
        plc_ip=plc_ip,
        poll_interval=poll_interval,
        app_version=APP_VERSION
    )


@app.route("/api/current")
def api_current():
    """Returns the single latest recorded sample (sub-millisecond from RAM if active)."""
    # 1. Try reading real-time live sample published by poller to RAM disk
    now_ts = datetime.now().timestamp()
    shm_paths = [Path("/dev/shm/pasteurizer_latest.json"), Path("/tmp/pasteurizer_latest.json")]
    for p in shm_paths:
        if p.is_file():
            try:
                # Must be fresh (modified within last 8 seconds)
                if (now_ts - p.stat().st_mtime) < 8.0:
                    with open(p, "r") as f:
                        data = json.load(f)
                    return jsonify({
                        "status": "ok",
                        "data": data,
                        "source": "ram",
                        "server_time": datetime.now().isoformat()
                    })
            except Exception:
                pass

    # 2. Fallback to SQLite database
    record = db.get_latest_record()
    if not record:
        return jsonify({
            "status": "waiting",
            "message": "No telemetry recorded yet in database.",
            "data": None
        })

    return jsonify({
        "status": "ok",
        "data": record,
        "source": "db",
        "server_time": datetime.now().isoformat()
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
    cpu_usage = psutil.cpu_percent(interval=None) if psutil else 0.0
    mem_used = round(psutil.virtual_memory().used / (1024 * 1024), 1) if psutil else 0.0
    mem_total = round(psutil.virtual_memory().total / (1024 * 1024), 1) if psutil else 0.0
    disk_free = round(psutil.disk_usage("/").free / (1024 * 1024 * 1024), 2) if psutil else 0.0
    disk_total = round(psutil.disk_usage("/").total / (1024 * 1024 * 1024), 2) if psutil else 0.0
    disk_pct = psutil.disk_usage("/").percent if psutil else 0.0

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
        "memory_used_mb": mem_used,
        "memory_total_mb": mem_total,
        "disk_free_gb": disk_free,
        "disk_total_gb": disk_total,
        "disk_used_pct": disk_pct
    })


@app.route("/api/system/minimize-kiosk", methods=["POST"])
def api_minimize_kiosk():
    """Minimizes the kiosk / browser window on the Raspberry Pi display."""
    import subprocess
    cmd = (
        "WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000 wlrctl toplevel minimize 2>/dev/null || "
        "xdotool key super+d 2>/dev/null || true"
    )
    try:
        subprocess.Popen(cmd, shell=True)
        return jsonify({"status": "ok", "message": "Minimize signal sent"})
    except Exception as exc:
        return jsonify({"status": "error", "error": str(exc)}), 500



@app.route("/api/export/csv")
def export_csv():
    """Export full process telemetry as CSV — all 58 SCADA instruments."""
    shift_arg = request.args.get("shift")
    if shift_arg:
        try:
            from src.reports.scheduler import get_shift_window
            sid = int(shift_arg) if shift_arg.isdigit() else None
            _, shift_title, start_dt, end_dt = get_shift_window(shift_id=sid)
            start = start_dt
            now = end_dt
            file_tag = f"shift{sid or 'current'}"
        except Exception:
            now = datetime.now()
            start = now - timedelta(hours=8)
            file_tag = "shift"
    else:
        hours = request.args.get("hours", default=8.0, type=float)
        now = datetime.now()
        start = now - timedelta(hours=hours)
        file_tag = f"{int(hours)}h"

    rows = db.get_records_between(start.isoformat(), now.isoformat())
    if not rows:
        rows = db.get_recent_records(limit=int(8 * 1200))

    try:
        from src.reports.scheduler import filter_records_interval
        rows = filter_records_interval(rows, interval_sec=3.0)
    except Exception:
        pass

    # Import column definitions from the report generator to stay in sync
    try:
        from src.reports.generator import ALL_COLUMNS, BOOL_FIELDS, _format_bool
    except ImportError:
        # Fallback: minimal export if generator not available
        ALL_COLUMNS = [
            ("Timestamp", "timestamp", None),
            ("Product", "product", None),
            ("Feed Flow (L/H)", "feed_flow", None),
            ("Holding In Temp (°C)", "holding_in_temp", None),
            ("Holding Out Temp (°C)", "holding_out_temp", None),
        ]
        BOOL_FIELDS = {}
        def _format_bool(field, val):
            return "ACTIVE" if val == 1 else "IDLE"

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row — every instrument label
    writer.writerow([col_name for col_name, _, _ in ALL_COLUMNS])

    # Data rows
    for r in rows:
        row_vals = []
        for col_name, field, _ in ALL_COLUMNS:
            val = r.get(field)
            if field in BOOL_FIELDS:
                val = _format_bool(field, val)
            elif val is None:
                val = ""
            row_vals.append(val)
        writer.writerow(row_vals)

    output.seek(0)
    filename = f"pasteurizer_telemetry_{file_tag}_{start.strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )



@app.route("/api/export/excel")
def export_excel():
    """Export formatted Excel report with summary KPIs and charts."""
    shift_arg = request.args.get("shift")
    step = request.args.get("step", default=1, type=int)

    if shift_arg:
        try:
            from src.reports.scheduler import get_shift_window
            sid = int(shift_arg) if shift_arg.isdigit() else None
            _, shift_title, start_dt, end_dt = get_shift_window(shift_id=sid)
            start = start_dt
            now = end_dt
            title = f"Pasteurizer Telemetry - {shift_title}"
        except Exception:
            now = datetime.now()
            start = now - timedelta(hours=8)
            title = "Pasteurizer Telemetry (Shift Window)"
    else:
        hours = request.args.get("hours", default=8.0, type=float)
        now = datetime.now()
        start = now - timedelta(hours=hours)
        title = f"Pasteurizer Telemetry ({int(hours)}h Window)"

    path = excel_gen.generate_report(
        start_iso=start.isoformat(),
        end_iso=now.isoformat(),
        report_title=title,
        sample_step=step
    )

    if not path or not path.exists():
        # Try wider window if empty
        path = excel_gen.generate_report(
            start_iso=(now - timedelta(days=7)).isoformat(),
            end_iso=now.isoformat(),
            report_title="Pasteurizer Telemetry (Full Available)",
            sample_step=step
        )

    if not path or not path.exists():
        return jsonify({"status": "error", "message": "No data available to generate Excel report"}), 404

    return send_file(str(path.resolve()), as_attachment=True)


@app.route("/api/export/pdf")
def export_pdf():
    """Export corporate audit-grade PDF with Anik Dairy & Goose logos."""
    shift_arg = request.args.get("shift")
    step = request.args.get("step", default=1, type=int)

    if shift_arg:
        try:
            from src.reports.scheduler import get_shift_window
            sid = int(shift_arg) if shift_arg.isdigit() else None
            _, shift_title, start_dt, end_dt = get_shift_window(shift_id=sid)
            start = start_dt
            now = end_dt
            title = f"Pasteurizer Audit Report - {shift_title}"
        except Exception:
            now = datetime.now()
            start = now - timedelta(hours=8)
            title = "Pasteurizer Quality Audit Report (Shift Window)"
    else:
        hours = request.args.get("hours", default=8.0, type=float)
        now = datetime.now()
        start = now - timedelta(hours=hours)
        title = f"Pasteurizer Quality Audit Report ({int(hours)}h Window)"

    path = pdf_gen.generate_pdf(
        start_iso=start.isoformat(),
        end_iso=now.isoformat(),
        report_title=title,
        sample_step=step
    )

    if not path or not path.exists():
        # Try wider window if empty
        path = pdf_gen.generate_pdf(
            start_iso=(now - timedelta(days=7)).isoformat(),
            end_iso=now.isoformat(),
            report_title="Pasteurizer Quality Audit Report (Full Available)",
            sample_step=step
        )

    if not path or not path.exists():
        return jsonify({"status": "error", "message": "No data available to generate PDF report"}), 404

    return send_file(str(path.resolve()), as_attachment=True)


# ==============================================================================
# PLC Remote Configuration & Tag Auto-Discovery Endpoints
# ==============================================================================

@app.route("/api/plc/current-config")
def get_current_plc_config():
    """Returns current PLC IP, mode, and tag configuration."""
    cfg = load_yaml(CONFIG_PATH)
    flat_tags = {}
    if TAGS_PATH.exists():
        try:
            with open(TAGS_PATH, "r") as f:
                data = json.load(f)
                tags_dict = data.get("tags", {}) if isinstance(data, dict) else {}
                for k, v in tags_dict.items():
                    if isinstance(v, dict):
                        flat_tags[k] = v.get("plc_tag", "")
                    else:
                        flat_tags[k] = str(v)
        except Exception:
            flat_tags = {}

    return jsonify({
        "status": "ok",
        "mode": cfg.get("plc", {}).get("mode", "mock"),
        "ip": cfg.get("plc", {}).get("ip", "192.168.1.50"),
        "tags": flat_tags
    })


@app.route("/api/plc/discover")
def api_discover_plcs():
    """Broadcasts to find EtherNet/IP devices on the subnet."""
    from src.plc.discovery import discover_plcs_on_network
    devices = discover_plcs_on_network()
    return jsonify({
        "status": "ok",
        "devices": devices,
        "count": len(devices)
    })


@app.route("/api/plc/tags")
def api_fetch_tags():
    """Extracts all tags from the specified Micro850 PLC IP."""
    ip = request.args.get("ip")
    if not ip:
        cfg = load_yaml(CONFIG_PATH)
        ip = cfg.get("plc", {}).get("ip", "192.168.1.50")

    from src.plc.discovery import fetch_tags_from_plc
    result = fetch_tags_from_plc(ip)
    return jsonify(result)


@app.route("/api/plc/test-read", methods=["POST"])
def api_test_read():
    """Performs a live test read on mapped PLC tags."""
    data = request.get_json() or {}
    ip = data.get("ip")
    tags = data.get("tags", {})
    if not ip or not tags:
        return jsonify({"success": False, "error": "Missing IP or tag mapping"}), 400

    from src.plc.discovery import test_tag_read
    res = test_tag_read(ip, tags)
    return jsonify(res)


@app.route("/api/plc/save-config", methods=["POST"])
def api_save_plc_config():
    """Saves new PLC IP and tags, switches to live, and restarts poller."""
    data = request.get_json() or {}
    ip = data.get("ip")
    tags = data.get("tags", {})
    mode = data.get("mode", "live")
    if not ip:
        return jsonify({"success": False, "error": "PLC IP is required"}), 400

    from src.plc.discovery import save_and_apply_plc_config
    res = save_and_apply_plc_config(ip, tags, mode=mode, restart_service=True)
    return jsonify(res)


if __name__ == "__main__":
    dash_cfg = config.get("dashboard", {})
    host = dash_cfg.get("host", "0.0.0.0")
    port = dash_cfg.get("port", 8080)
    app.run(host=host, port=port, debug=False)

