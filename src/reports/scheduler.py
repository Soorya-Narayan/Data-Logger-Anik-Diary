"""
Automated Report Scheduler & Email Dispatcher.
Triggers shift reports and daily summaries according to plant shift hours.
Optionally emails the generated Excel file via SMTP.
"""

import sys
import yaml
import smtplib
import logging
from typing import Optional, List, Union, Tuple
from pathlib import Path
from email.message import EmailMessage
from datetime import datetime, timedelta

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


def get_shift_window(
    shift_id: Optional[int] = None,
    ref_time: Optional[datetime] = None
) -> Tuple[int, str, datetime, datetime]:
    """Calculate the precise start and end datetimes for plant shifts:
      • 1st Shift: 06:30 AM to 02:00 PM (14:00)
      • 2nd Shift: 02:00 PM to 10:00 PM (22:00)
      • 3rd Shift: 10:00 PM to 06:30 AM (crosses midnight)
    """
    now = ref_time or datetime.now()
    today = now.date()
    yesterday = today - timedelta(days=1)

    t_0630 = datetime.combine(today, datetime.strptime("06:30", "%H:%M").time())
    t_1400 = datetime.combine(today, datetime.strptime("14:00", "%H:%M").time())
    t_2200 = datetime.combine(today, datetime.strptime("22:00", "%H:%M").time())
    y_2200 = datetime.combine(yesterday, datetime.strptime("22:00", "%H:%M").time())

    if shift_id == 1:
        start = t_0630 if now >= t_0630 else datetime.combine(yesterday, datetime.strptime("06:30", "%H:%M").time())
        end = t_1400 if now >= t_0630 else datetime.combine(yesterday, datetime.strptime("14:00", "%H:%M").time())
        return 1, "1st Shift (06:30 AM - 02:00 PM)", start, end

    elif shift_id == 2:
        start = t_1400 if now >= t_1400 else datetime.combine(yesterday, datetime.strptime("14:00", "%H:%M").time())
        end = t_2200 if now >= t_1400 else datetime.combine(yesterday, datetime.strptime("22:00", "%H:%M").time())
        return 2, "2nd Shift (02:00 PM - 10:00 PM)", start, end

    elif shift_id == 3:
        if now < t_0630:
            start = y_2200
            end = t_0630
        elif now < t_2200:
            start = y_2200
            end = t_0630
        else:
            start = t_2200
            end = datetime.combine(today + timedelta(days=1), datetime.strptime("06:30", "%H:%M").time())
        return 3, "3rd Shift (10:00 PM - 06:30 AM)", start, end

    else:
        # Auto-detect which shift just concluded based on current clock time
        current_minute = now.hour * 60 + now.minute
        m_0630 = 6 * 60 + 30
        m_1400 = 14 * 60
        m_2200 = 22 * 60

        if m_0630 <= current_minute < m_1400:
            return 3, "3rd Shift (10:00 PM - 06:30 AM)", y_2200, t_0630
        elif m_1400 <= current_minute < m_2200:
            return 1, "1st Shift (06:30 AM - 02:00 PM)", t_0630, t_1400
        else:
            if current_minute >= m_2200:
                return 2, "2nd Shift (02:00 PM - 10:00 PM)", t_1400, t_2200
            else:
                y_1400 = datetime.combine(yesterday, datetime.strptime("14:00", "%H:%M").time())
                return 2, "2nd Shift (02:00 PM - 10:00 PM)", y_1400, y_2200


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

        try:
            from src.reports.pdf_generator import PDFReportGenerator
            self.pdf_generator = PDFReportGenerator(
                db_manager=self.db,
                output_dir=out_dir,
                plant_info=self.config.get("plant", {})
            )
        except Exception as exc:
            logger.warning("Could not initialize PDFReportGenerator: %s", exc)
            self.pdf_generator = None

    def generate_shift_package(
        self,
        shift_id: Optional[int] = None,
        ref_time: Optional[datetime] = None
    ) -> List[Path]:
        """Generate both corporate audit PDF report and full CSV telemetry log for a specific plant shift,

        and dispatch them together in a SINGLE consolidated email.
        """
        sid, shift_name, start, end = get_shift_window(shift_id=shift_id, ref_time=ref_time)
        shift_tag = f"shift{sid}_{start.strftime('%Y%m%d_%H%M')}"
        attachments: List[Path] = []
        out_dir = Path(self.config.get("reporting", {}).get("output_dir", "reports"))
        out_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Generating report package for %s: %s to %s", shift_name, start.isoformat(), end.isoformat())

        # 1. Generate Shift Audit PDF Report
        if self.pdf_generator:
            try:
                pdf_title = f"Pasteurizer Audit Report - Shift {sid} ({start.strftime('%d-%b-%Y')})"
                pdf_path = self.pdf_generator.generate_pdf(
                    start_iso=start.isoformat(),
                    end_iso=end.isoformat(),
                    report_title=pdf_title,
                    sample_step=1
                )
                if pdf_path and pdf_path.exists():
                    attachments.append(pdf_path)
                    logger.info("Attached Shift Audit PDF: %s", pdf_path.name)
            except Exception as exc:
                logger.error("Failed to generate PDF for %s: %s", shift_name, exc)

        # 2. Generate Shift CSV Telemetry Log (All 58 columns at 3-second intervals)
        try:
            import csv
            from src.reports.generator import ALL_COLUMNS, BOOL_FIELDS, _format_bool

            csv_filename = f"anik_pasteurizer_telemetry_{shift_tag}.csv"
            csv_path = out_dir / csv_filename

            rows = self.db.get_records_between(start.isoformat(), end.isoformat())
            if not rows:
                logger.warning("No records found in database for %s (%s to %s)", shift_name, start.isoformat(), end.isoformat())
            else:
                rows = filter_records_interval(rows, interval_sec=3.0)
                with open(csv_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([col_name for col_name, _, _ in ALL_COLUMNS])
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
                logger.info("Generated Shift CSV telemetry log: %s (%d records at 3s intervals)", csv_path.name, len(rows))
                attachments.append(csv_path)
        except Exception as exc:
            logger.error("Failed to generate CSV for %s: %s", shift_name, exc)

        # 3. Transmit consolidated shift package via Email
        if attachments and self.config.get("reporting", {}).get("email", {}).get("enabled", False):
            subject = f"{shift_name} Process Audit & Telemetry Report ({start.strftime('%d-%b-%Y')})"
            plant_name = self.config.get("plant", {}).get("name", "Anik Dairy")
            unit_name = self.config.get("plant", {}).get("unit", "10 KL Pasteurizer")

            file_summaries = []
            for p in attachments:
                size_kb = p.stat().st_size / 1024
                size_str = f"{size_kb / 1024:.1f} MB" if size_kb > 1024 else f"{size_kb:.0f} KB"
                file_summaries.append(f"  • {p.name} ({p.suffix.upper().replace('.', '')} - {size_str})")

            body_text = (
                f"Hello,\n\n"
                f"Please find attached the automated shift process report package for the {unit_name} at {plant_name} (Bhopal Plant).\n\n"
                f"Shift Details:\n"
                f"• Operational Shift: {shift_name}\n"
                f"• Shift Window: {start.strftime('%d-%b-%Y %I:%M %p')} to {end.strftime('%d-%b-%Y %I:%M %p')}\n"
                f"• Generation Time: {datetime.now().strftime('%d-%b-%Y %I:%M:%S %p')}\n"
                f"• Equipment: {unit_name}\n\n"
                f"Attached Reports ({len(attachments)}):\n"
                f"{chr(10).join(file_summaries)}\n\n"
                f"Contents Included:\n"
                f"1. Executive PDF Audit Report: Visualized temperature profiles, Critical Control Point (TT06 CCP) holding compliance, alarms, and plant hydraulics.\n"
                f"2. Shift CSV Telemetry Log: Full 58-column instrument SCADA dataset sampled at uniform 3-second intervals.\n\n"
                f"This is an automated transmission from the on-premise industrial data logger node."
            )
            self.send_email(attachments, subject, body_text=body_text)

        return attachments

    def generate_shift_report(self, shift_hours_back: int = 8) -> Optional[Path]:
        """Generate a report for the previous shift window (backward compatibility)."""
        return self.generate_shift_package()
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

    def generate_daily_csv_report(self, hours_back: int = 24, send_mail: bool = True) -> Optional[Path]:
        """Generate a 24-hour raw CSV telemetry log covering all 58 SCADA instruments."""
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
            # Write 58-instrument header row
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
        if send_mail and self.config.get("reporting", {}).get("email", {}).get("enabled", False):
            self.send_email(file_path, title)

        return file_path

    def generate_daily_package(self, hours_back: int = 24) -> List[Path]:
        """Generate both corporate audit PDF report and 24-hour CSV telemetry log,

        and dispatch them together in a SINGLE consolidated email.
        """
        now = datetime.now()
        start = now - timedelta(hours=hours_back)
        date_str = start.strftime("%d-%b-%Y")
        attachments: List[Path] = []

        # 1. Generate Audit PDF Report
        if self.pdf_generator:
            try:
                pdf_title = f"Pasteurizer Quality Audit Report ({hours_back}h Window)"
                pdf_path = self.pdf_generator.generate_pdf(
                    start_iso=start.isoformat(),
                    end_iso=now.isoformat(),
                    report_title=pdf_title,
                    sample_step=1
                )
                if pdf_path and pdf_path.exists():
                    attachments.append(pdf_path)
                    logger.info("Attached Audit PDF to daily package: %s", pdf_path.name)
            except Exception as exc:
                logger.error("Failed to generate PDF for daily package: %s", exc)

        # 2. Generate 24h CSV Telemetry Log (All 58 columns at 3-second intervals)
        try:
            csv_path = self.generate_daily_csv_report(hours_back=hours_back, send_mail=False)
            if csv_path and csv_path.exists():
                attachments.append(csv_path)
                logger.info("Attached Telemetry CSV to daily package: %s", csv_path.name)
        except Exception as exc:
            logger.error("Failed to generate CSV for daily package: %s", exc)

        # 3. Transmit consolidated package in a SINGLE email
        if attachments and self.config.get("reporting", {}).get("email", {}).get("enabled", False):
            subject = f"Daily Process Audit & Telemetry Report ({date_str})"
            self.send_email(attachments, subject)

        return attachments

    def send_email(
        self,
        file_paths: Union[Path, List[Path], str],
        subject: str,
        body_text: Optional[str] = None
    ) -> bool:
        """Send generated report(s) via SMTP with auto-detected MIME type in a single email."""
        mail_cfg = self.config.get("reporting", {}).get("email", {})
        if not mail_cfg.get("enabled", False):
            logger.info("Email dispatch disabled in configuration.")
            return False

        if isinstance(file_paths, (str, Path)):
            raw_paths = [Path(file_paths)]
        else:
            raw_paths = [Path(p) for p in file_paths if p]

        valid_paths = [p for p in raw_paths if p.exists()]
        if not valid_paths:
            logger.warning("No valid report files found to send via email.")
            return False

        try:
            processed_attachments: List[Path] = []
            file_summaries: List[str] = []

            for p in valid_paths:
                actual_p = p
                # If file exceeds 20MB, compress to .zip
                if p.stat().st_size > 20 * 1024 * 1024:
                    import zipfile
                    zip_path = p.with_name(f"{p.stem}.zip")
                    logger.info("File '%s' is %d MB (>20 MB). Compressing to '%s'...", p.name, p.stat().st_size // (1024 * 1024), zip_path.name)
                    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                        zf.write(p, arcname=p.name)
                    actual_p = zip_path

                size_kb = actual_p.stat().st_size / 1024
                size_str = f"{size_kb / 1024:.1f} MB" if size_kb > 1024 else f"{size_kb:.0f} KB"
                file_summaries.append(f"  • {actual_p.name} ({actual_p.suffix.upper().replace('.', '')} - {size_str})")
                processed_attachments.append(actual_p)

            logger.info(
                "Sending consolidated report email with %d attachment(s) [%s] to %s...",
                len(processed_attachments),
                ", ".join(p.name for p in processed_attachments),
                mail_cfg.get("recipients")
            )

            msg = EmailMessage()
            plant_name = self.config.get("plant", {}).get("name", "Anik Dairy")
            unit_name = self.config.get("plant", {}).get("unit", "10 KL Pasteurizer")

            msg["Subject"] = f"[{plant_name}] {subject}"
            msg["From"] = mail_cfg.get("sender")
            msg["To"] = ", ".join(mail_cfg.get("recipients", []))

            if not body_text:
                files_block = "\n".join(file_summaries)
                body_text = (
                    f"Hello,\n\n"
                    f"Please find attached the automated daily process telemetry reports for the {unit_name} at {plant_name} (Bhopal Plant).\n\n"
                    f"Report Package Summary:\n"
                    f"• Equipment: {unit_name}\n"
                    f"• Generated At: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"• Attached Reports ({len(processed_attachments)}):\n"
                    f"{files_block}\n\n"
                    f"Contents Included:\n"
                    f"1. Executive PDF Audit Report: Visualized temperature profiles, Critical Control Point (TT06 CCP) status, alarms, and plant hydraulics.\n"
                    f"2. Daily CSV Telemetry Log: Full 58-column instrument SCADA export sampled at 3-second logging intervals.\n\n"
                    f"This is an automated transmission from the on-premise industrial data logger node."
                )

            msg.set_content(body_text)

            # Attach all processed files to the single EmailMessage
            for p in processed_attachments:
                ext = p.suffix.lower()
                if ext == ".csv":
                    maintype, subtype = "text", "csv"
                elif ext == ".pdf":
                    maintype, subtype = "application", "pdf"
                elif ext == ".zip":
                    maintype, subtype = "application", "zip"
                else:
                    maintype, subtype = "application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"

                with open(p, "rb") as f:
                    file_data = f.read()
                    msg.add_attachment(
                        file_data,
                        maintype=maintype,
                        subtype=subtype,
                        filename=p.name
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

            logger.info("Consolidated email with %d attachment(s) sent successfully to %s.", len(processed_attachments), mail_cfg.get("recipients"))
            return True

        except Exception as exc:
            logger.error("Failed to transmit email report: %s", exc)
            return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    scheduler = ReportScheduler()

    # CLI dispatch: --shift [1|2|3], --daily (24h package), --daily-csv, --pdf
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg == "--shift":
            shift_num = None
            if len(sys.argv) > 2 and sys.argv[2].isdigit():
                shift_num = int(sys.argv[2])
            scheduler.generate_shift_package(shift_id=shift_num)
        elif arg in ("--daily", "--package", "--all", "--24h"):
            scheduler.generate_daily_package(hours_back=24)
        elif arg in ("--daily-csv", "--csv"):
            scheduler.generate_daily_csv_report()
        elif arg == "--pdf":
            now = datetime.now()
            start = now - timedelta(hours=24)
            if scheduler.pdf_generator:
                p = scheduler.pdf_generator.generate_pdf(
                    start.isoformat(), now.isoformat(), f"Quality Audit Report ({start.strftime('%d-%b-%Y')})"
                )
                if p:
                    scheduler.send_email(p, f"Quality Audit Report PDF ({start.strftime('%d-%b-%Y')})")
        else:
            print(f"Unknown option '{arg}'. Usage: python scheduler.py [--shift [1|2|3] | --daily | --daily-csv | --pdf]")
    else:
        # Default scheduled execution triggers the shift package for the concluded shift
        scheduler.generate_shift_package()
