"""
SCADA Process Report Generator for 10 KL Pasteurizer (Anik Dairy, Bhopal).
Builds structured audit-grade Excel (.xlsx) workbooks with summary KPIs,
log data tables matching the reference PHE-3 layout, and embedded openpyxl trend charts.
"""

import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.chart import LineChart, Reference, Series
from openpyxl.utils import get_column_letter

from src.storage.db import DatabaseManager

logger = logging.getLogger("ReportGenerator")


class ExcelReportGenerator:
    """Creates formatted shift/daily reports in Excel matching the plant's SCADA format."""

    def __init__(self, db_manager: DatabaseManager, output_dir: str = "reports", plant_info: Optional[dict] = None):
        self.db = db_manager
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.plant_info = plant_info or {
            "name": "Anik Dairy - Bhopal",
            "unit": "10 KL Pasteurizer",
            "reference_line": "PHE-3"
        }

    def generate_report(
        self,
        start_iso: str,
        end_iso: str,
        report_title: str = "Shift Process Report",
        sample_step: int = 1
    ) -> Optional[Path]:
        """
        Generate an Excel report for the given time window.
        
        Args:
            start_iso: Start timestamp in ISO format (e.g. '2026-09-22T06:00:00')
            end_iso: End timestamp in ISO format
            report_title: Title header for the report
            sample_step: Downsampling factor (1 = every second, 5 = every 5s, etc.)
            
        Returns:
            Path to generated .xlsx file or None if no data.
        """
        logger.info("Generating report '%s' from %s to %s...", report_title, start_iso, end_iso)
        raw_records = self.db.get_records_between(start_iso, end_iso)

        if not raw_records:
            logger.warning("No records found in database between %s and %s", start_iso, end_iso)
            return None

        # Downsample if requested (e.g. 1-second data downsampled to 5s or 10s for compact sheets)
        records = raw_records[::sample_step] if sample_step > 1 else raw_records
        df = pd.DataFrame(records)

        # 1. Calculate Summary KPIs
        kpis = self._calculate_kpis(df, raw_records)

        # 2. Build workbook
        wb = openpyxl.Workbook()
        ws_summary = wb.active
        ws_summary.title = "Executive Summary"
        ws_data = wb.create_sheet(title="Process Telemetry Log")

        self._build_summary_sheet(ws_summary, report_title, start_iso, end_iso, kpis)
        self._build_data_sheet(ws_data, df)
        self._embed_trend_chart(ws_summary, ws_data, len(df))

        # 3. Save workbook
        start_dt = datetime.fromisoformat(start_iso.replace("Z", ""))
        date_str = start_dt.strftime("%Y%m%d_%H%M")
        clean_title = report_title.replace(" ", "_").lower()
        filename = f"{clean_title}_{date_str}.xlsx"
        target_path = self.output_dir / filename

        wb.save(target_path)
        logger.info("Report generated successfully at: %s", target_path)
        return target_path

    def _calculate_kpis(self, df: pd.DataFrame, all_records: List[Dict]) -> Dict[str, Any]:
        """Compute production statistics from raw data."""
        total_samples = len(all_records)
        if total_samples == 0:
            return {}

        # Estimated total volume: flow in L/hr / 3600 per 1-second record
        total_liters = 0.0
        prod_seconds = 0
        divert_count = 0
        in_divert = False
        divert_seconds = 0
        cip_seconds = 0
        prod_holding_in_temps = []
        prod_holding_out_temps = []

        for r in all_records:
            flow = r.get("milk_flow") or 0.0
            fdv1 = r.get("fdv1_status") or 0
            fdv2 = r.get("fdv2_status") or 0
            cip = r.get("cip_status") or 0
            t_in = r.get("holding_in_temp")
            t_out = r.get("holding_out_temp")

            if cip == 1:
                cip_seconds += 1

            if fdv1 == 1 and fdv2 == 1 and flow > 1000:
                prod_seconds += 1
                total_liters += (flow / 3600.0)
                if in_divert:
                    in_divert = False
                if t_in is not None:
                    prod_holding_in_temps.append(t_in)
                if t_out is not None:
                    prod_holding_out_temps.append(t_out)
            else:
                if flow > 1000 and (fdv1 == 0 or fdv2 == 0):
                    divert_seconds += 1
                    if not in_divert:
                        divert_count += 1
                        in_divert = True

        avg_in = sum(prod_holding_in_temps) / len(prod_holding_in_temps) if prod_holding_in_temps else 0.0
        avg_out = sum(prod_holding_out_temps) / len(prod_holding_out_temps) if prod_holding_out_temps else 0.0

        return {
            "total_samples": total_samples,
            "total_milk_liters": round(total_liters, 1),
            "total_milk_kl": round(total_liters / 1000.0, 2),
            "production_time_min": round(prod_seconds / 60.0, 1),
            "divert_count": divert_count,
            "divert_time_min": round(divert_seconds / 60.0, 1),
            "cip_time_min": round(cip_seconds / 60.0, 1),
            "avg_holding_in_c": round(avg_in, 2),
            "avg_holding_out_c": round(avg_out, 2),
        }

    def _build_summary_sheet(self, ws, report_title: str, start_iso: str, end_iso: str, kpis: Dict[str, Any]):
        """Format the high-level KPI overview sheet."""
        ws.views.sheetView[0].showGridLines = True

        # Styles
        title_font = Font(name="Calibri", size=16, bold=True, color="1E3A8A")
        subtitle_font = Font(name="Calibri", size=11, bold=True, color="475569")
        header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        kpi_label_font = Font(name="Calibri", size=10, bold=True, color="334155")
        kpi_val_font = Font(name="Calibri", size=12, bold=True, color="0F172A")
        thin_border = Border(
            left=Side(style="thin", color="CBD5E1"),
            right=Side(style="thin", color="CBD5E1"),
            top=Side(style="thin", color="CBD5E1"),
            bottom=Side(style="thin", color="CBD5E1")
        )

        # Title Block
        ws["A1"] = self.plant_info.get("name", "Anik Dairy - Bhopal")
        ws["A1"].font = title_font
        ws["A2"] = f"{self.plant_info.get('unit', '10 KL Pasteurizer')} - {report_title} (Ref: {self.plant_info.get('reference_line', 'PHE-3')})"
        ws["A2"].font = subtitle_font
        ws["A3"] = f"Logging Window: {start_iso} to {end_iso}"
        ws["A3"].font = Font(name="Calibri", size=9, italic=True, color="64748B")

        # KPI Summary Table
        ws["A5"] = "PROCESS RUN KPI SUMMARY"
        ws["A5"].font = header_font
        ws["A5"].fill = header_fill
        ws.merge_cells("A5:B5")

        rows = [
            ("Total Milk Processed", f"{kpis.get('total_milk_kl', 0.0)} KL ({kpis.get('total_milk_liters', 0):,} Liters)"),
            ("Active Production Time", f"{kpis.get('production_time_min', 0.0)} Minutes"),
            ("Avg Holding In Temp", f"{kpis.get('avg_holding_in_c', 0.0)} °C (Target: 81.0 - 81.5°C)"),
            ("Avg Holding Out Temp", f"{kpis.get('avg_holding_out_c', 0.0)} °C"),
            ("FDV Diversion Events", f"{kpis.get('divert_count', 0)} events ({kpis.get('divert_time_min', 0.0)} min total)"),
            ("CIP Active Duration", f"{kpis.get('cip_time_min', 0.0)} Minutes"),
            ("Total Logged Samples", f"{kpis.get('total_samples', 0):,} records"),
        ]

        curr_row = 6
        for label, val in rows:
            ws[f"A{curr_row}"] = label
            ws[f"A{curr_row}"].font = kpi_label_font
            ws[f"A{curr_row}"].border = thin_border
            ws[f"A{curr_row}"].fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

            ws[f"B{curr_row}"] = val
            ws[f"B{curr_row}"].font = kpi_val_font
            ws[f"B{curr_row}"].border = thin_border
            ws[f"B{curr_row}"].alignment = Alignment(horizontal="right")
            curr_row += 1

        ws.column_dimensions["A"].width = 28
        ws.column_dimensions["B"].width = 36

    def _build_data_sheet(self, ws, df: pd.DataFrame):
        """Build the full telemetric log table formatted like the PHE-3 SCADA report."""
        ws.views.sheetView[0].showGridLines = True

        headers = [
            ("Date & Time", "timestamp"),
            ("Product", "product"),
            ("Milk Flow (L/hr)", "milk_flow"),
            ("Holding In (°C)", "holding_in_temp"),
            ("Holding Out (°C)", "holding_out_temp"),
            ("FDV-1 Pos", "fdv1_status"),
            ("FDV-1 Reason", "fdv1_reason"),
            ("FDV-2 Pos", "fdv2_status"),
            ("FDV-2 Reason", "fdv2_reason"),
            ("CIP Status", "cip_status"),
            ("CIP Step", "cip_step"),
            ("Process Status", "status"),
        ]

        header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
        header_font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
        data_font = Font(name="Calibri", size=9)
        zebra_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")

        # Write header row
        for col_idx, (col_name, _) in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # Write data rows
        for row_idx, row in df.iterrows():
            excel_row = row_idx + 2
            is_even = (excel_row % 2 == 0)

            for col_idx, (_, field) in enumerate(headers, 1):
                val = row.get(field, "")
                # Format valve positions
                if field in ("fdv1_status", "fdv2_status"):
                    val = "FORWARD" if val == 1 else "DIVERT"
                elif field == "cip_status":
                    val = "ACTIVE" if val == 1 else "IDLE"

                cell = ws.cell(row=excel_row, column=col_idx, value=val)
                cell.font = data_font

                if is_even:
                    cell.fill = zebra_fill

                # Number formatting
                if field == "milk_flow" and isinstance(val, (int, float)):
                    cell.number_format = "#,##0.0"
                    cell.alignment = Alignment(horizontal="right")
                elif field in ("holding_in_temp", "holding_out_temp") and isinstance(val, (int, float)):
                    cell.number_format = "0.00"
                    cell.alignment = Alignment(horizontal="right")
                elif field in ("fdv1_status", "fdv2_status", "cip_status"):
                    cell.alignment = Alignment(horizontal="center")

        # Auto-fit column widths
        for col_idx in range(1, len(headers) + 1):
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = 18

        ws.column_dimensions["A"].width = 24  # Timestamp
        ws.column_dimensions["L"].width = 45  # Process Status

    def _embed_trend_chart(self, ws_target, ws_source, total_rows: int):
        """Embed an openpyxl LineChart of holding temperatures and flow."""
        if total_rows < 2:
            return

        chart = LineChart()
        chart.title = "Pasteurization Thermal Profile & Flow"
        chart.style = 13
        chart.y_axis.title = "Temperature (°C)"
        chart.x_axis.number_format = "HH:MM:SS"
        chart.x_axis.majorTimeUnit = "seconds"
        chart.width = 22
        chart.height = 12

        # Data references (Column 4 = Holding In, Column 5 = Holding Out)
        # Limit chart reference to first 1000 rows to keep workbook lightweight
        max_chart_rows = min(total_rows + 1, 1000)
        data = Reference(ws_source, min_col=4, min_row=1, max_col=5, max_row=max_chart_rows)
        dates = Reference(ws_source, min_col=1, min_row=2, max_row=max_chart_rows)

        chart.add_data(data, titles_from_data=True)
        chart.set_categories(dates)

        # Style lines
        s1 = chart.series[0]
        s1.graphicalProperties.line.solidFill = "FB923C"  # Holding In (Orange)
        s1.graphicalProperties.line.width = 20000

        s2 = chart.series[1]
        s2.graphicalProperties.line.solidFill = "38BDF8"  # Holding Out (Blue)
        s2.graphicalProperties.line.width = 20000

        # Place chart on Executive Summary sheet
        ws_target.add_chart(chart, "D5")
