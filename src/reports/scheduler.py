"""
Automated Report Scheduler & Email Dispatcher.
Triggers shift reports and daily summaries according to plant shift hours.
Optionally emails the generated Excel file via SMTP.
"""

import sys
import yaml
import smtplib
import logging
from pathlib import Path
from email.message import EmailMessage
from datetime import datetime, timedelta
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.storage.db import DatabaseManager
from src.reports.generator import ExcelReportGenerator

logger = logging.getLogger("ReportScheduler")


def filter_records_interval(records: list, interval_sec: float = 3.0) -> list:
    """Filters records to guarantee exact target sampling cadence (e.g. 3-second intervals).

    Downsamples sub-3s historical data to 3-second intervals,
    while retaining all records if already sampled at 3-second cadence.
    """
    if not records:
        return []
    filtered = []
    last_ts = None
    for r in records:
        ts_str = r.get("timestamp")
        if not ts_str:
            continue
        try:
            dt = datetime.fromisoformat(ts_str)
            ts_epoch = dt.timestamp()
        except Exception:
            ts_epoch = None

        if last_ts is None or ts_epoch is None or (ts_epoch - last_ts) >= (interval_sec - 0.5):
            filtered.append(r)
            if ts_epoch is not None:
                last_ts = ts_epoch
    return filtered


class ReportScheduler:
    """Manages scheduled report generation and optional email transmission."""

    def __init__(self, config_path: str = "config/config.yaml"):
        project_root = Path(__file__).resolve().parent.parent.parent
        self.config_path = Path(config_path)
        if not self.config_path.is_absolute():
            self.config_path = project_root / self.config_path

        if self.config_path.exists():
            with open(self.config_path, "r") as f:
                self.config = yaml.safe_load(f) or {}
        else:
            self.config = {}

        reporting_cfg = self.config.setdefault("reporting", {})
        reporting_cfg.setdefault("email", {})
        db_path = self.config.get("storage", {}).get("db_path", "data/pasteurizer_data.db")
        if not Path(db_path).is_absolute():
            db_path = str(project_root / db_path)

        out_dir = reporting_cfg.get("output_dir", "reports")
        if not Path(out_dir).is_absolute():
            out_dir = str(project_root / out_dir)
            reporting_cfg["output_dir"] = out_dir

        self.db = DatabaseManager(db_path=db_path)
        self.generator = ExcelReportGenerator(
            db_manager=self.db,
            output_dir=out_dir,
            plant_info=self.config.get("plant", {})
        )

    def generate_shift_report(self, shift_hours_back: int = 8) -> Optional[Path]:
        """Generate a report for the previous shift window."""
        now = datetime.now()
        start = now - timedelta(hours=shift_hours_back)
        title = f"Shift Report ({shift_hours_back}h Window)"
        step = self.config.get("reporting", {}).get("excel_sample_interval_sec", 1)

        path = self.generator.generate_report(
            start_iso=start.isoformat(),
            end_iso=now.isoformat(),
            report_title=title,
            sample_step=step
        )

        if path and self.config.get("reporting", {}).get("email", {}).get("enabled", False):
            self.send_email(path, title)

        return path

    def generate_daily_report(self) -> Optional[Path]:
        """Generate a 24-hour summary report."""
        now = datetime.now()
        start = now - timedelta(hours=24)
        title = f"Daily 24h Summary ({start.strftime('%Y-%m-%d')})"
        step = self.config.get("reporting", {}).get("excel_sample_interval_sec", 1)

        path = self.generator.generate_report(
            start_iso=start.isoformat(),
            end_iso=now.isoformat(),
            report_title=title,
            sample_step=step
        )

        if path and self.config.get("reporting", {}).get("email", {}).get("enabled", False):
            self.send_email(path, title)

        return path

    def generate_daily_csv_report(self, hours_back: int = 24) -> Optional[Path]:
        """Generate a 24-hour raw CSV telemetry log covering all 38 SCADA instruments and email it."""
        import csv
        from src.reports.generator import ALL_COLUMNS, BOOL_FIELDS, _format_bool

        now = datetime.now()
        start = now - timedelta(hours=hours_back)
        out_dir = Path(self.config.get("reporting", {}).get("output_dir", "reports"))
        out_dir.mkdir(parents=True, exist_ok=True)

        filename = f"anik_pasteurizer_telemetry_24h_{start.strftime('%Y%m%d')}.csv"
        file_path = out_dir / filename

        rows = self.db.get_records_between(start.isoformat(), now.isoformat())
        if not rows:
            logger.warning("No records found in database for 24h window %s to %s", start.isoformat(), now.isoformat())
            return None

        # Ensure telemetry report data is sampled strictly at 3-second intervals
        rows = filter_records_interval(rows, interval_sec=3.0)

        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # Write 38-instrument header row
            writer.writerow([col_name for col_name, _, _ in ALL_COLUMNS])

            # Write data rows
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

        logger.info("Generated 24-hour CSV telemetry log: %s (%d records at 3s intervals)", file_path, len(rows))

        title = f"Daily 24h Process Telemetry CSV ({start.strftime('%d-%b-%Y')})"
        if self.config.get("reporting", {}).get("email", {}).get("enabled", False):
            self.send_email(file_path, title)

        return file_path

    def send_email(self, file_path: Path, subject: str) -> bool:
        """Send generated report via SMTP with auto-detected MIME type."""
        mail_cfg = self.config.get("reporting", {}).get("email", {})
        if not mail_cfg.get("enabled", False):
            logger.info("Email dispatch disabled in configuration.")
            return False

        try:
            # Prevent email bounce: if file exceeds 20MB, automatically compress to .zip
            actual_path = file_path
            if file_path.stat().st_size > 20 * 1024 * 1024:
                import zipfile
                zip_path = file_path.with_name(f"{file_path.stem}.zip")
                logger.info(
                    "Report file '%s' is %d MB (>20 MB). Compressing to '%s' for safe SMTP delivery...",
                    file_path.name,
                    file_path.stat().st_size // (1024 * 1024),
                    zip_path.name
                )
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.write(file_path, arcname=file_path.name)
                actual_path = zip_path

            logger.info("Sending report '%s' via SMTP to %s...", actual_path.name, mail_cfg.get("recipients"))
            msg = EmailMessage()
            msg["Subject"] = f"[{self.config.get('plant', {}).get('name')}] {subject}"
            msg["From"] = mail_cfg.get("sender")
            msg["To"] = ", ".join(mail_cfg.get("recipients", []))
            msg.set_content(
                f"Hello,\n\n"
                f"Attached is the automated daily process telemetry report from the 10 KL Pasteurizer Data Logger at Anik Dairy (Bhopal).\n\n"
                f"Report Details:\n"
                f"• Equipment: {self.config.get('plant', {}).get('unit')}\n"
                f"• Generated At: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"• File Name: {actual_path.name}\n"
                f"• Format: {actual_path.suffix.upper().replace('.', '')}\n\n"
                f"This is an automated transmission from the on-premise industrial data logger node."
            )

            # Determine MIME type based on file extension
            ext = actual_path.suffix.lower()
            if ext == ".csv":
                maintype, subtype = "text", "csv"
            elif ext == ".pdf":
                maintype, subtype = "application", "pdf"
            elif ext == ".zip":
                maintype, subtype = "application", "zip"
            else:
                maintype, subtype = "application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"

            with open(actual_path, "rb") as f:
                file_data = f.read()
                msg.add_attachment(
                    file_data,
                    maintype=maintype,
                    subtype=subtype,
                    filename=actual_path.name
                )

            server = mail_cfg.get("smtp_server")
            port = int(mail_cfg.get("smtp_port", 587))
            use_tls = mail_cfg.get("use_tls", True)
            use_ssl = mail_cfg.get("use_ssl", False) or port == 465

            if use_ssl:
                import ssl
                ssl_ctx = ssl.create_default_context()
                with smtplib.SMTP_SSL(server, port, context=ssl_ctx, timeout=30) as smtp:
                    if mail_cfg.get("username") and mail_cfg.get("password"):
                        smtp.login(mail_cfg["username"], mail_cfg["password"])
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(server, port, timeout=30) as smtp:
                    if use_tls:
                        smtp.starttls()
                    if mail_cfg.get("username") and mail_cfg.get("password"):
                        smtp.login(mail_cfg["username"], mail_cfg["password"])
                    smtp.send_message(msg)

            logger.info("Email sent successfully to %s.", mail_cfg.get("recipients"))
            return True

        except Exception as exc:
            logger.error("Failed to transmit email report: %s", exc)
            return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    scheduler = ReportScheduler()

    # CLI dispatch: --daily-csv, --daily (Excel), or default shift
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ("--daily-csv", "--csv"):
            scheduler.generate_daily_csv_report()
        elif arg == "--daily":
            # Check configured report format preference
            fmt = scheduler.config.get("reporting", {}).get("format", "csv").lower()
            if "csv" in fmt:
                scheduler.generate_daily_csv_report()
            if "excel" in fmt or "xlsx" in fmt:
                scheduler.generate_daily_report()
        elif arg == "--shift":
            scheduler.generate_shift_report()
        else:
            print(f"Unknown option '{arg}'. Usage: python scheduler.py [--daily-csv | --daily | --shift]")
    else:
        scheduler.generate_daily_csv_report()
