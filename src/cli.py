"""
Command-line utility for Anik Dairy 10 KL Pasteurizer Logger.
Provides diagnostics, ad-hoc report generation, and PLC testing commands.
"""

import sys
import json
import yaml
import argparse
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.plc import get_plc_client
from src.storage import DatabaseManager
from src.reports import ExcelReportGenerator, ReportScheduler


def load_config():
    with open("config/config.yaml", "r") as f:
        config = yaml.safe_load(f)
    with open("config/tags.json", "r") as f:
        tags = json.load(f)
    return config, tags


def cmd_test_plc(args):
    """Test connection and tag reading on configured PLC."""
    config, tags = load_config()
    mode = config.get("plc", {}).get("mode", "mock").upper()
    ip = config.get("plc", {}).get("ip")
    print(f"\n[PLC Test] Initializing {mode} client (Target IP: {ip})...")

    client = get_plc_client(config, tags)
    try:
        connected = client.connect()
        if not connected:
            print("[PLC Test] ERROR: Unable to establish connection to PLC.")
            sys.exit(1)

        print("[PLC Test] Connection SUCCESSFUL.")
        print("[PLC Test] Attempting single poll cycle...")
        data = client.read_tags()
        print("\n--- Tag Read Results ---")
        for k, v in data.items():
            print(f"  {k:20s}: {v}")
        print("------------------------\n")
        client.disconnect()
        print("[PLC Test] Disconnected cleanly.")
    except Exception as exc:
        print(f"[PLC Test] EXCEPTION: {exc}")
        sys.exit(1)


def cmd_db_stats(args):
    """Show database statistics and total recorded samples."""
    config, _ = load_config()
    db_path = config.get("storage", {}).get("db_path", "data/pasteurizer_data.db")
    db = DatabaseManager(db_path=db_path)

    latest = db.get_latest_record()
    total = 0
    conn = db._get_connection()
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM pasteurizer_logs;")
        total = cursor.fetchone()[0]
    finally:
        conn.close()

    print("\n--- SQLite Database Status ---")
    print(f"  Path: {Path(db_path).resolve()}")
    print(f"  Total Records: {total:,}")
    if latest:
        print(f"  Latest Timestamp: {latest.get('timestamp')}")
        print(f"  Current Status:   {latest.get('status')}")
        print(f"  Milk Flow:        {latest.get('milk_flow')} L/hr")
        print(f"  Holding In:       {latest.get('holding_in_temp')} °C")
    else:
        print("  Database currently empty.")
    print("------------------------------\n")


def cmd_generate_report(args):
    """Trigger manual Excel, PDF, or CSV report generation."""
    config, _ = load_config()
    db_path = config.get("storage", {}).get("db_path", "data/pasteurizer_data.db")
    db = DatabaseManager(db_path=db_path)
    hours = args.hours
    fmt = getattr(args, "format", "excel").lower()

    print(f"\n[Report] Generating {fmt.upper()} report for last {hours} hours...")
    now = datetime.now()
    start = now - timedelta(hours=hours)

    if fmt == "pdf":
        from src.reports.pdf_generator import PDFReportGenerator
        gen = PDFReportGenerator(db_manager=db, plant_info=config.get("plant"))
        path = gen.generate_pdf(
            start_iso=start.isoformat(),
            end_iso=now.isoformat(),
            report_title=f"Manual Quality Audit ({hours}h Window)",
            sample_step=args.sample_step
        )
    elif fmt == "csv":
        import csv
        rows = db.get_records_between(start.isoformat(), now.isoformat())
        if not rows:
            rows = db.get_recent_records(limit=int(hours * 3600))
        path = Path("reports") / f"manual_log_{now.strftime('%Y%m%d_%H%M')}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Timestamp", "Product", "Milk Flow (L/hr)", "Holding In Temp (C)",
                "Holding Out Temp (C)", "FDV-1 Status", "FDV-1 Reason",
                "FDV-2 Status", "FDV-2 Reason", "CIP Status", "CIP Step", "Process Status"
            ])
            for r in rows:
                writer.writerow([
                    r.get("timestamp"), r.get("product"), r.get("milk_flow"),
                    r.get("holding_in_temp"), r.get("holding_out_temp"),
                    "FORWARD" if r.get("fdv1_status") == 1 else "DIVERT",
                    r.get("fdv1_reason"),
                    "FORWARD" if r.get("fdv2_status") == 1 else "DIVERT",
                    r.get("fdv2_reason"),
                    "ACTIVE" if r.get("cip_status") == 1 else "IDLE",
                    r.get("cip_step"), r.get("status")
                ])
    else:
        scheduler = ReportScheduler()
        gen = scheduler.generator
        path = gen.generate_report(
            start_iso=start.isoformat(),
            end_iso=now.isoformat(),
            report_title=f"Manual Report ({hours}h Window)",
            sample_step=args.sample_step
        )

    if path and Path(path).exists():
        print(f"[Report] Generated successfully: {Path(path).resolve()}")
    else:
        print("[Report] No data logged in the specified time window.")


def main():
    parser = argparse.ArgumentParser(description="Anik Dairy Pasteurizer Logger CLI Utility")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # test-plc
    p_test = subparsers.add_parser("test-plc", help="Test PLC connectivity and read sample tags")
    p_test.set_defaults(func=cmd_test_plc)

    # db-stats
    p_stats = subparsers.add_parser("db-stats", help="Show SQLite database size and record counts")
    p_stats.set_defaults(func=cmd_db_stats)

    # generate-report
    p_report = subparsers.add_parser("generate-report", help="Generate ad-hoc report (Excel, PDF, CSV)")
    p_report.add_argument("--hours", type=float, default=1.0, help="Hours of history to include (default: 1.0)")
    p_report.add_argument("--format", type=str, choices=["excel", "pdf", "csv"], default="excel", help="Output format: excel, pdf, or csv (default: excel)")
    p_report.add_argument("--sample-step", type=int, default=1, help="Downsampling step in seconds (default: 1)")
    p_report.set_defaults(func=cmd_generate_report)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
