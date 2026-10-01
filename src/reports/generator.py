"""
SCADA Process Report Generator for 10 KL Pasteurizer (Anik Dairy, Bhopal).
Builds structured audit-grade Excel (.xlsx) workbooks with summary KPIs,
full 30-instrument log data tables, and embedded openpyxl trend charts.
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


# ---------------------------------------------------------------------------
# Complete column map: (Excel Header,  DB column name,  number format)
# ---------------------------------------------------------------------------
ALL_COLUMNS = [
    # Identification
    ("Date & Time",                 "timestamp",                    None),
    ("Process State",               "product",                      None),
    ("Status",                      "status",                       None),

    # Section 1 – Thermal Profile & Temperature Transmitters (TT01 – TT16)
    ("TT-01 Product In (°C)",       "temp_tt01",                    "0.00"),
    ("TT-02 Regen 1 In (°C)",       "temp_tt02",                    "0.00"),
    ("TT-03 Regen 2 In (°C)",       "temp_tt03",                    "0.00"),
    ("TT-04 TBC (°C)",              "temp_tt04",                    "0.00"),
    ("TT-05 Holding In (°C)",       "temp_tt05",                    "0.00"),
    ("TT-06 Holding Out1 (°C)",     "temp_tt06",                    "0.00"),
    ("TT-07 TBC (°C)",              "temp_tt07",                    "0.00"),
    ("TT-08 Holding Out2 (°C)",     "temp_tt08",                    "0.00"),
    ("TT-09 TBC (°C)",              "temp_tt09",                    "0.00"),
    ("TT-10 TBC (°C)",              "temp_tt10",                    "0.00"),
    ("TT-11 Regen 1 Out (°C)",      "temp_tt11",                    "0.00"),
    ("TT-12 Product Out (°C)",      "temp_tt12",                    "0.00"),
    ("TT-13 Not Connected",         "temp_tt13",                    "0.00"),
    ("TT-14 Not Connected",         "temp_tt14",                    "0.00"),
    ("TT-15 Chiller In (°C)",       "temp_tt15",                    "0.00"),
    ("TT-16 Chiller Out (°C)",      "temp_tt16",                    "0.00"),
    ("Delta T (°C)",                "delta_t",                      "0.00"),

    # Legacy temp aliases (fallback compatibility)
    ("Hold In Legacy (°C)",         "holding_in_temp",              "0.00"),
    ("Hold Out Legacy (°C)",        "holding_out_temp",             "0.00"),

    # Section 2 – Pressures
    ("PT-01 Raw Milk (Bar)",        "press_raw_milk_pt01",          "0.000"),
    ("PT-02 Regen R2 (Bar)",        "press_regen_r2_pt02",          "0.000"),
    ("PT-03 Holding In (Bar)",      "press_holding_in_pt03",        "0.000"),
    ("PT-04 Chilled Milk (Bar)",    "press_chilled_milk_pt04",      "0.000"),
    ("PT-05 Hot Water (Bar)",       "press_hot_water_pt05",         "0.000"),
    ("PT-06 Chilling (Bar)",        "press_chilling_pt06",          "0.000"),

    # Section 3 – Process Control / Mass Flow / Level
    ("Feed Flow (L/H)",             "feed_flow",                    "#,##0.0"),
    ("Feed Flow Legacy (L/H)",      "milk_flow",                    "#,##0.0"),
    ("Product Totalizer (L)",       "product_tot",                  "#,##0.0"),
    ("Steam CV (%)",                "steam_cv",                     "0.0"),
    ("Deodoriser Level (%)",        "deodoriser_level",             "0.0"),
    ("Regen Efficiency (%)",        "regen_efficiency",             "0.0"),

    # Section 4 – Setpoints
    ("SP-01 Heating Temp (°C)",     "sp_heating_temp",              "0.0"),
    ("SP-02 Chill FDV Div (°C)",    "sp_chill_fdv_diversion",       "0.0"),
    ("SP-03 Heat FDV Hys (°C)",     "sp_heating_fdv_hys",           "0.0"),
    ("SP-04 Chill Press (Bar)",     "sp_chilling_pressure",         "0.00"),
    ("SP-05 Regen R1 Press (Bar)",  "sp_regen_r1_pressure",         "0.00"),

    # Section 5 – Valves & Interlocks
    ("HOT FDV Position",            "hot_fdv_open",                 None),   # BOOL -> FWD/DIVERT
    ("HOT FDV Status",              "hot_fdv_status",               None),
    ("FDV-1 Position",              "fdv1_status",                  None),   # legacy BOOL
    ("FDV-1 Reason",                "fdv1_reason",                  None),
    ("CHILL FDV Position",          "chill_fdv_open",               None),
    ("CHILL FDV Status",            "chill_fdv_status",             None),
    ("FDV-2 Position",              "fdv2_status",                  None),
    ("FDV-2 Reason",                "fdv2_reason",                  None),
    ("Force Circulation",           "force_circulation",            None),
    ("Force Forward",               "force_forward",                None),
    ("CIP Status",                  "cip_status",                   None),
    ("CIP Step",                    "cip_step",                     None),

    # Alarms / Failures
    ("Failures / Active Alarms",    "failures",                     None),
    ("Master Alarm",                "alarm_main",                   None),
    ("FDV-1 Alarm",                 "alarm_fdv1",                   None),
    ("High Press Alarm 1",          "alarm_high_press1",            None),
    ("High Press Alarm 2",          "alarm_high_press2",            None),
    ("FDV-1 Trip",                  "trip_fdv1",                    None),
    ("FDV-2 Trip",                  "trip_fdv2",                    None),
]

# Boolean/integer fields that should be rendered as readable text
BOOL_FIELDS = {
    "hot_fdv_open": ("FORWARD", "DIVERTED"),
    "chill_fdv_open": ("FORWARD", "DIVERTED"),
    "fdv1_status": ("FORWARD", "DIVERTED"),
    "fdv2_status": ("FORWARD", "DIVERTED"),
    "force_circulation": ("ACTIVE", "OFF"),
    "force_forward": ("ACTIVE", "OFF"),
    "cip_status": ("ACTIVE", "IDLE"),
    "alarm_main": ("ALARM", "OK"),
    "alarm_fdv1": ("ALARM", "OK"),
    "alarm_high_press1": ("ALARM", "OK"),
    "alarm_high_press2": ("ALARM", "OK"),
    "trip_fdv1": ("TRIP", "OK"),
    "trip_fdv2": ("TRIP", "OK"),
}


def _format_bool(field: str, val) -> str:
    if val is None:
        return "--"
    true_label, false_label = BOOL_FIELDS[field]
    return true_label if val == 1 else false_label


class ExcelReportGenerator:
    """Creates formatted shift/daily reports in Excel with all 30 SCADA instruments."""

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
        """Generate a clean Excel (.xlsx) workbook containing the exact same 58-column

        SCADA telemetry data as the CSV export, without charts or extra summary tabs.
        """
        logger.info("Generating Excel report '%s' from %s to %s...", report_title, start_iso, end_iso)
        raw_records = self.db.get_records_between(start_iso, end_iso)

        if not raw_records:
            logger.warning("No records found in database between %s and %s", start_iso, end_iso)
            return None

        from src.reports.scheduler import filter_records_interval
        raw_records = filter_records_interval(raw_records, interval_sec=3.0)
        records = raw_records[::sample_step] if sample_step > 1 else raw_records

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Telemetry Data"
        ws.views.sheetView[0].showGridLines = True
        ws.freeze_panes = "A2"

        header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        header_font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")

        # Write header row matching all 58 columns
        headers = [col_name for col_name, _, _ in ALL_COLUMNS]
        ws.append(headers)
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)
        ws.row_dimensions[1].height = 28

        # Write data rows
        for r in records:
            row_vals = []
            for col_name, field, _ in ALL_COLUMNS:
                val = r.get(field)
                if field in BOOL_FIELDS:
                    val = _format_bool(field, val)
                elif field == "timestamp" and isinstance(val, str) and "T" in val:
                    val = val.replace("T", " ")[:19]
                elif val is None or (isinstance(val, float) and pd.isna(val)):
                    val = ""
                row_vals.append(val)
            ws.append(row_vals)

        # Set column widths & auto-filter
        for col_idx, (col_name, field, _) in enumerate(ALL_COLUMNS, 1):
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = max(len(col_name) + 3, 14)
        ws.column_dimensions["A"].width = 22

        total_rows = len(records) + 1
        ws.auto_filter.ref = f"A1:{get_column_letter(len(ALL_COLUMNS))}{total_rows}"

        start_dt = datetime.fromisoformat(start_iso.replace("Z", ""))
        date_str = start_dt.strftime("%Y%m%d_%H%M")
        clean_title = report_title.replace(" ", "_").lower()
        filename = f"{clean_title}_{date_str}.xlsx"
        target_path = self.output_dir / filename

        wb.save(target_path)
        logger.info("Excel report generated successfully at: %s (%d records)", target_path, len(records))
        return target_path

    def generate_csv(
        self,
        start_iso: str,
        end_iso: str,
        report_title: str = "Shift Process Report",
        sample_step: int = 1
    ) -> Optional[Path]:
        """Generate a full-fidelity CSV export with all 30 SCADA instruments."""
        logger.info("Generating CSV '%s' from %s to %s...", report_title, start_iso, end_iso)
        raw_records = self.db.get_records_between(start_iso, end_iso)
        if not raw_records:
            logger.warning("No records found for CSV between %s and %s", start_iso, end_iso)
            return None

        records = raw_records[::sample_step] if sample_step > 1 else raw_records
        rows = []
        for r in records:
            row = {}
            for col_name, field, _ in ALL_COLUMNS:
                val = r.get(field)
                if field in BOOL_FIELDS:
                    val = _format_bool(field, val)
                elif val is None:
                    val = ""
                row[col_name] = val
            rows.append(row)

        df = pd.DataFrame(rows)
        start_dt = datetime.fromisoformat(start_iso.replace("Z", ""))
        date_str = start_dt.strftime("%Y%m%d_%H%M")
        clean_title = report_title.replace(" ", "_").lower()
        filename = f"{clean_title}_{date_str}.csv"
        target_path = self.output_dir / filename
        df.to_csv(target_path, index=False)
        logger.info("CSV generated at: %s", target_path)
        return target_path

    def _calculate_kpis(self, df: pd.DataFrame, all_records: List[Dict]) -> Dict[str, Any]:
        """Compute production statistics from raw data."""
        total_samples = len(all_records)
        if total_samples == 0:
            return {}

        total_liters = 0.0
        prod_seconds = 0
        divert_count = 0
        in_divert = False
        divert_seconds = 0
        cip_seconds = 0
        prod_holding_in_temps = []
        prod_holding_out_temps = []
        all_press_pt03 = []
        all_steam_cv = []
        alarm_count = 0

        for r in all_records:
            flow = r.get("feed_flow") or r.get("milk_flow") or 0.0
            fdv1 = r.get("hot_fdv_open") or r.get("fdv1_status") or 0
            fdv2 = r.get("chill_fdv_open") or r.get("fdv2_status") or 0
            cip = r.get("cip_status") or 0
            t_in = r.get("temp_tt05") or r.get("temp_holding_in_tt04") or r.get("holding_in_temp")
            t_out = r.get("temp_tt06") or r.get("temp_holding_out1_tt05") or r.get("holding_out_temp")
            pt03 = r.get("press_holding_in_pt03")
            scv = r.get("steam_cv")
            alarm = r.get("alarm_main") or 0

            if cip == 1:
                cip_seconds += 1
            if alarm == 1:
                alarm_count += 1
            if pt03 is not None:
                all_press_pt03.append(pt03)
            if scv is not None:
                all_steam_cv.append(scv)

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
        avg_pt03 = sum(all_press_pt03) / len(all_press_pt03) if all_press_pt03 else 0.0
        avg_steam = sum(all_steam_cv) / len(all_steam_cv) if all_steam_cv else 0.0

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
            "avg_holding_press_bar": round(avg_pt03, 3),
            "avg_steam_cv_pct": round(avg_steam, 1),
            "alarm_seconds": alarm_count,
        }

    def _build_summary_sheet(self, ws, report_title: str, start_iso: str, end_iso: str, kpis: Dict[str, Any]):
        """Format the high-level KPI overview sheet."""
        ws.views.sheetView[0].showGridLines = True

        RED   = "D7262D"
        NAVY  = "152238"
        GOLD  = "C28E3A"
        CREAM = "FAF7F2"

        title_font    = Font(name="Calibri", size=16, bold=True, color=NAVY)
        subtitle_font = Font(name="Calibri", size=11, bold=True, color="475569")
        header_fill   = PatternFill(start_color=NAVY, end_color=NAVY, fill_type="solid")
        header_font   = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        kpi_label_font = Font(name="Calibri", size=10, bold=True, color="334155")
        kpi_val_font   = Font(name="Calibri", size=11, bold=True, color=NAVY)
        alarm_font     = Font(name="Calibri", size=11, bold=True, color=RED)
        thin_border = Border(
            left=Side(style="thin", color="CBD5E1"),
            right=Side(style="thin", color="CBD5E1"),
            top=Side(style="thin", color="CBD5E1"),
            bottom=Side(style="thin", color="CBD5E1")
        )
        cream_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

        ws["A1"] = self.plant_info.get("name", "Anik Dairy - Bhopal")
        ws["A1"].font = title_font
        ws["A2"] = f"{self.plant_info.get('unit', '10 KL Pasteurizer')} — {report_title} (Ref: {self.plant_info.get('reference_line', 'PHE-3')})"
        ws["A2"].font = subtitle_font
        ws["A3"] = f"Logging Window: {start_iso}  →  {end_iso}  |  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ws["A3"].font = Font(name="Calibri", size=9, italic=True, color="64748B")

        # Section header
        ws["A5"] = "PROCESS RUN KPI SUMMARY — ALL 30 INSTRUMENTS"
        ws["A5"].font = header_font
        ws["A5"].fill = header_fill
        ws.merge_cells("A5:B5")

        rows = [
            ("Total Milk Processed",         f"{kpis.get('total_milk_kl', 0.0)} KL  ({kpis.get('total_milk_liters', 0):,} Liters)", False),
            ("Active Production Time",        f"{kpis.get('production_time_min', 0.0)} min", False),
            ("Avg Holding Outlet Temp TT06",  f"{kpis.get('avg_holding_out_c', 0.0)} °C", False),
            ("Avg Holding Inlet Temp TT05",   f"{kpis.get('avg_holding_in_c', 0.0)} °C", False),
            ("Avg Holding Inlet Press PT03",  f"{kpis.get('avg_holding_press_bar', 0.0)} Bar", False),
            ("Avg Steam Control Valve CV",    f"{kpis.get('avg_steam_cv_pct', 0.0)} %", False),
            ("FDV Diversion Events",          f"{kpis.get('divert_count', 0)} events  ({kpis.get('divert_time_min', 0.0)} min total)", False),
            ("CIP Active Duration",           f"{kpis.get('cip_time_min', 0.0)} min", False),
            ("Master Alarm Active (seconds)", f"{kpis.get('alarm_seconds', 0)} s", True),
            ("Total Logged Samples",          f"{kpis.get('total_samples', 0):,} records  @ 1-second resolution", False),
        ]

        curr_row = 6
        for label, val, is_alarm in rows:
            ws[f"A{curr_row}"] = label
            ws[f"A{curr_row}"].font = kpi_label_font
            ws[f"A{curr_row}"].border = thin_border
            ws[f"A{curr_row}"].fill = cream_fill

            ws[f"B{curr_row}"] = val
            ws[f"B{curr_row}"].font = alarm_font if is_alarm and kpis.get("alarm_seconds", 0) > 0 else kpi_val_font
            ws[f"B{curr_row}"].border = thin_border
            ws[f"B{curr_row}"].alignment = Alignment(horizontal="right")
            curr_row += 1

        ws.column_dimensions["A"].width = 32
        ws.column_dimensions["B"].width = 40

    def _build_data_sheet(self, ws, df: pd.DataFrame):
        """Build the full 30-instrument telemetric log table."""
        ws.views.sheetView[0].showGridLines = True
        ws.freeze_panes = "A2"

        NAVY  = "152238"
        RED   = "D7262D"

        header_fill = PatternFill(start_color=NAVY, end_color=NAVY, fill_type="solid")
        header_font = Font(name="Calibri", size=9, bold=True, color="FFFFFF")
        data_font   = Font(name="Calibri", size=8)
        zebra_fill  = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
        alarm_fill  = PatternFill(start_color="FEF2F2", end_color="FEF2F2", fill_type="solid")
        alarm_font  = Font(name="Calibri", size=8, bold=True, color=RED)

        # Write header row
        for col_idx, (col_name, field, _) in enumerate(ALL_COLUMNS, 1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        ws.row_dimensions[1].height = 30

        for row_idx, row in df.iterrows():
            excel_row = row_idx + 2
            is_even = (excel_row % 2 == 0)
            has_alarm = (row.get("alarm_main") == 1)

            for col_idx, (col_name, field, fmt) in enumerate(ALL_COLUMNS, 1):
                val = row.get(field)

                # Format booleans to readable text
                if field in BOOL_FIELDS:
                    val = _format_bool(field, val)
                elif val is None or (isinstance(val, float) and pd.isna(val)):
                    val = ""

                cell = ws.cell(row=excel_row, column=col_idx, value=val)

                if has_alarm:
                    cell.fill = alarm_fill
                    cell.font = alarm_font
                elif is_even:
                    cell.fill = zebra_fill
                    cell.font = data_font
                else:
                    cell.font = data_font

                if fmt and isinstance(val, (int, float)):
                    cell.number_format = fmt
                    cell.alignment = Alignment(horizontal="right")
                elif field == "timestamp":
                    cell.alignment = Alignment(horizontal="left")

        # Column widths
        col_widths = {
            "timestamp": 22, "product": 14, "status": 12,
        }
        for col_idx, (col_name, field, _) in enumerate(ALL_COLUMNS, 1):
            col_letter = get_column_letter(col_idx)
            width = col_widths.get(field, 16)
            ws.column_dimensions[col_letter].width = width

        # Auto-filter on header row
        ws.auto_filter.ref = f"A1:{get_column_letter(len(ALL_COLUMNS))}1"

    def _build_csv_ready_sheet(self, ws, df: pd.DataFrame):
        """Minimal sheet suitable for copy-paste to CSV or further analysis tools."""
        ws.views.sheetView[0].showGridLines = True

        header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
        header_font = Font(name="Calibri", size=9, bold=True, color="FFFFFF")
        data_font   = Font(name="Calibri", size=8)

        for col_idx, (col_name, field, _) in enumerate(ALL_COLUMNS, 1):
            cell = ws.cell(row=1, column=col_idx, value=col_name)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

        for row_idx, row in df.iterrows():
            excel_row = row_idx + 2
            for col_idx, (_, field, fmt) in enumerate(ALL_COLUMNS, 1):
                val = row.get(field)
                if field in BOOL_FIELDS:
                    val = _format_bool(field, val)
                elif val is None or (isinstance(val, float) and pd.isna(val)):
                    val = ""
                cell = ws.cell(row=excel_row, column=col_idx, value=val)
                cell.font = data_font

        for col_idx in range(1, len(ALL_COLUMNS) + 1):
            ws.column_dimensions[get_column_letter(col_idx)].width = 16
        ws.column_dimensions["A"].width = 22

    def _embed_trend_chart(self, ws_target, ws_source, total_rows: int):
        """Embed an openpyxl LineChart of the 4 primary telemetry curves."""
        if total_rows < 2:
            return

        chart = LineChart()
        chart.title = "Pasteurization Thermal Profile & Flow (TT01, TT05, TT08, Feed Flow)"
        chart.style = 13
        chart.y_axis.title = "Temperature (°C)"
        chart.x_axis.number_format = "HH:MM:SS"
        chart.width = 26
        chart.height = 14

        max_chart_rows = min(total_rows + 1, 1000)

        # Column indices in ws_source (1-based):
        # TT01 = col 4, TT06 = col 9, TT16 = col 19, Feed Flow = col 29
        for col_idx, color, label in [
            (4,  "D7262D", "TT01 Product In (°C)"),
            (9,  "C28E3A", "TT06 Holding Out1 (°C)"),
            (19, "0284C7", "TT16 Chiller Out (°C)"),
            (29, "006837", "Feed Flow (L/H)"),
        ]:
            data_ref = Reference(ws_source, min_col=col_idx, min_row=1, max_row=max_chart_rows)
            series = Series(data_ref, title=label)
            series.graphicalProperties.line.solidFill = color
            series.graphicalProperties.line.width = 18000
            chart.series.append(series)

        dates = Reference(ws_source, min_col=1, min_row=2, max_row=max_chart_rows)
        chart.set_categories(dates)

        ws_target.add_chart(chart, "D6")
