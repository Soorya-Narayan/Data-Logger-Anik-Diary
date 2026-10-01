"""
Audit-Grade PDF Process Report Generator for 10 KL Pasteurizer (Anik Dairy, Bhopal).
Covers all 30 dashboard instruments: TT01–TT09, PT01–PT06, Feed Flow, Totalizer,
Steam CV, Deodoriser Level, Regen Efficiency, Delta-T, SP01–SP05, HOT/CHILL FDV,
Force modes, and all Alarm/Failure fields.
"""

import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image,
    KeepTogether, PageBreak, HRFlowable
)
from reportlab.pdfgen import canvas

from src.storage.db import DatabaseManager

logger = logging.getLogger("PDFReportGenerator")

# ── Anik Dairy Brand Colours ──────────────────────────────────────────────────
ANIK_RED   = colors.HexColor("#D7262D")
ANIK_NAVY  = colors.HexColor("#152238")
ANIK_GOLD  = colors.HexColor("#C28E3A")
ANIK_GREEN = colors.HexColor("#006837")
ANIK_CREAM = colors.HexColor("#FAF7F2")
SLATE      = colors.HexColor("#475569")
LIGHT_GREY = colors.HexColor("#F1F5F9")
BORDER_CLR = colors.HexColor("#CBD5E1")
WHITE      = colors.white
BLACK      = colors.HexColor("#0F172A")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ── Column Definitions ────────────────────────────────────────────────────────
# (PDF header label, DB field name, text-align: "C"=center "R"=right "L"=left)
PDF_SECTIONS = [
    # ── TIMESTAMPS & STATE ───────────────────────────────────────────────────
    ("Timestamp",               "timestamp",                "C"),
    ("State",                   "product",                  "C"),

    # ── TEMPERATURES ─────────────────────────────────────────────────────────
    ("TT01\nProd In\n(°C)",     "temp_product_in_tt01",     "R"),
    ("TT04\nHold In\n(°C)",     "temp_holding_in_tt04",     "R"),
    ("TT05\nHold Out1\n(°C)",   "temp_holding_out1_tt05",   "R"),
    ("TT06\nHold Out2\n(°C)",   "temp_holding_out2_tt06",   "R"),
    ("TT07\nChill Milk\n(°C)",  "temp_chilled_milk_tt07",   "R"),
    ("TT08\nChilling\n(°C)",    "temp_chilling_tt08",       "R"),
    ("TT09\nHot Water\n(°C)",   "temp_hot_water_tt09",      "R"),
    ("TT03\nRegen R2\n(°C)",    "temp_regen_r2_tt03",       "R"),
    ("ΔT\n(°C)",                "delta_t",                  "R"),

    # ── PRESSURES ────────────────────────────────────────────────────────────
    ("PT01\nRaw Milk\n(Bar)",   "press_raw_milk_pt01",      "R"),
    ("PT02\nRegen R2\n(Bar)",   "press_regen_r2_pt02",      "R"),
    ("PT03\nHold In\n(Bar)",    "press_holding_in_pt03",    "R"),
    ("PT04\nChill\n(Bar)",      "press_chilled_milk_pt04",  "R"),
    ("PT05\nHot H2O\n(Bar)",    "press_hot_water_pt05",     "R"),
    ("PT06\nChilling\n(Bar)",   "press_chilling_pt06",      "R"),

    # ── FLOW / CONTROL / LEVEL ───────────────────────────────────────────────
    ("Feed Flow\n(L/H)",        "feed_flow",                "R"),
    ("Product\nTot (L)",        "product_tot",              "R"),
    ("Steam\nCV (%)",           "steam_cv",                 "R"),
    ("Deodoriser\nLevel (%)",   "deodoriser_level",         "R"),
    ("Regen\nEff (%)",          "regen_efficiency",         "R"),

    # ── SETPOINTS ────────────────────────────────────────────────────────────
    ("SP Heat\nTemp (°C)",      "sp_heating_temp",          "R"),
    ("SP Chill\nFDV (°C)",      "sp_chill_fdv_diversion",   "R"),
    ("SP Heat\nHys (°C)",       "sp_heating_fdv_hys",       "R"),
    ("SP Chill\nPress (Bar)",   "sp_chilling_pressure",     "R"),
    ("SP Regen\nPress (Bar)",   "sp_regen_r1_pressure",     "R"),

    # ── VALVES / INTERLOCKS ───────────────────────────────────────────────────
    ("HOT\nFDV",                "hot_fdv_open",             "C"),
    ("CHILL\nFDV",              "chill_fdv_open",           "C"),
    ("Force\nCirc",             "force_circulation",        "C"),
    ("Force\nFwd",              "force_forward",            "C"),
    ("CIP",                     "cip_status",               "C"),

    # ── ALARMS / FAILURES ─────────────────────────────────────────────────────
    ("Failures / Active Alarms",    "failures",             "L"),
]

BOOL_FIELDS = {
    "hot_fdv_open":     ("FWD", "DIV"),
    "chill_fdv_open":   ("FWD", "DIV"),
    "fdv1_status":      ("FWD", "DIV"),
    "fdv2_status":      ("FWD", "DIV"),
    "force_circulation":("ON",  "OFF"),
    "force_forward":    ("ON",  "OFF"),
    "cip_status":       ("ACT", "IDLE"),
    "alarm_main":       ("ALM", "OK"),
    "alarm_fdv1":       ("ALM", "OK"),
    "trip_fdv1":        ("TRIP","OK"),
    "trip_fdv2":        ("TRIP","OK"),
}

NUM_FIELDS = {
    "temp_product_in_tt01", "temp_regen_r2_tt03", "temp_holding_in_tt04",
    "temp_holding_out1_tt05", "temp_holding_out2_tt06", "temp_chilled_milk_tt07",
    "temp_chilling_tt08", "temp_hot_water_tt09", "delta_t",
    "press_raw_milk_pt01", "press_regen_r2_pt02", "press_holding_in_pt03",
    "press_chilled_milk_pt04", "press_hot_water_pt05", "press_chilling_pt06",
    "feed_flow", "milk_flow", "product_tot", "steam_cv", "deodoriser_level",
    "regen_efficiency",
    "sp_heating_temp", "sp_chill_fdv_diversion", "sp_heating_fdv_hys",
    "sp_chilling_pressure", "sp_regen_r1_pressure",
}


def _fmt(field: str, val) -> str:
    """Format a single DB value for PDF display."""
    if val is None:
        return "--"
    if field in BOOL_FIELDS:
        t, f = BOOL_FIELDS[field]
        return t if val == 1 else f
    if field in NUM_FIELDS:
        try:
            fval = float(val)
            if field.startswith("press_") or field.startswith("sp_chilling") or field.startswith("sp_regen"):
                return f"{fval:.3f}"
            if field in ("feed_flow", "milk_flow", "product_tot"):
                return f"{fval:,.1f}"
            return f"{fval:.2f}"
        except (TypeError, ValueError):
            return str(val)
    return str(val)[:40] if val else "--"


# ── Page Footer Canvas ────────────────────────────────────────────────────────
class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            super().showPage()
        super().save()

    def draw_page_number(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 7.5)
        self.setFillColor(SLATE)
        text = f"Anik Dairy 10 KL Pasteurizer SCADA Log  |  Page {self._pageNumber} of {page_count}"
        self.drawRightString(11 * inch - 0.5 * inch, 0.35 * inch, text)
        self.drawString(0.5 * inch, 0.35 * inch, "Confidential — Quality Assurance & Regulatory Audit Use Only")
        self.setStrokeColor(BORDER_CLR)
        self.setLineWidth(0.5)
        self.line(0.5 * inch, 0.5 * inch, 11 * inch - 0.5 * inch, 0.5 * inch)
        self.restoreState()


# ── Main Generator ─────────────────────────────────────────────────────────────
class PDFReportGenerator:
    """Generates landscape audit-grade PDF reports covering all 30 SCADA instruments."""

    def __init__(self, db_manager: DatabaseManager, output_dir: str = "reports", plant_info: Optional[dict] = None):
        self.db = db_manager
        self.output_dir = Path(output_dir)
        if not self.output_dir.is_absolute():
            self.output_dir = PROJECT_ROOT / self.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.plant_info = plant_info or {
            "name": "Anik Dairy - Bhopal",
            "unit": "10 KL Pasteurizer",
            "reference_line": "PHE-3"
        }

        anik_p1 = PROJECT_ROOT / "docs/assets/anik_logo.png"
        anik_p2 = PROJECT_ROOT / "src/dashboard/static/img/anik_logo.png"
        self.anik_logo_path = anik_p1 if anik_p1.exists() else anik_p2

        goose_p1 = PROJECT_ROOT / "docs/assets/goose_logo.png"
        goose_p2 = PROJECT_ROOT / "src/dashboard/static/img/goose_logo.png"
        self.goose_logo_path = goose_p1 if goose_p1.exists() else goose_p2

    def generate_pdf(
        self,
        start_iso: str,
        end_iso: str,
        report_title: str = "Shift Process Report",
        sample_step: int = 1
    ) -> Optional[Path]:
        logger.info("Generating PDF '%s' from %s to %s...", report_title, start_iso, end_iso)
        raw_records = self.db.get_records_between(start_iso, end_iso)

        if not raw_records:
            logger.warning("No records found for PDF between %s and %s", start_iso, end_iso)
            return None

        start_dt = datetime.fromisoformat(start_iso.replace("Z", ""))
        date_str = start_dt.strftime("%Y%m%d_%H%M")
        clean_title = report_title.replace(" ", "_").lower()
        filename = f"{clean_title}_{date_str}.pdf"
        target_path = self.output_dir / filename

        doc = SimpleDocTemplate(
            str(target_path),
            pagesize=landscape(letter),
            leftMargin=0.4 * inch,
            rightMargin=0.4 * inch,
            topMargin=0.4 * inch,
            bottomMargin=0.6 * inch
        )

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle("DocTitle", parent=styles["Normal"],
            fontName="Helvetica-Bold", fontSize=14, leading=17,
            textColor=ANIK_NAVY, alignment=1)
        subtitle_style = ParagraphStyle("DocSub", parent=styles["Normal"],
            fontName="Helvetica", fontSize=9.5, leading=12,
            textColor=SLATE, alignment=1)
        meta_style = ParagraphStyle("DocMeta", parent=styles["Normal"],
            fontName="Helvetica", fontSize=7.5, leading=10,
            textColor=SLATE, alignment=1)
        hdr_style = ParagraphStyle("TblHdr", parent=styles["Normal"],
            fontName="Helvetica-Bold", fontSize=7, leading=9,
            textColor=WHITE, alignment=1)
        cell_c = ParagraphStyle("CellC", parent=styles["Normal"],
            fontName="Helvetica", fontSize=6.5, leading=8,
            textColor=BLACK, alignment=1)
        cell_r = ParagraphStyle("CellR", parent=styles["Normal"],
            fontName="Helvetica", fontSize=6.5, leading=8,
            textColor=BLACK, alignment=2)
        cell_l = ParagraphStyle("CellL", parent=styles["Normal"],
            fontName="Helvetica", fontSize=6.5, leading=8,
            textColor=BLACK, alignment=0)
        alarm_cell = ParagraphStyle("AlarmCell", parent=styles["Normal"],
            fontName="Helvetica-Bold", fontSize=6.5, leading=8,
            textColor=ANIK_RED, alignment=1)

        STYLE_MAP = {"C": cell_c, "R": cell_r, "L": cell_l}

        elements = []

        # ── Header ────────────────────────────────────────────────────────────
        anik_img = None
        if self.anik_logo_path.exists():
            try:
                anik_img = Image(str(self.anik_logo_path), width=1.0 * inch, height=0.55 * inch)
            except Exception as e:
                logger.warning("Anik logo load failed: %s", e)

        goose_img = None
        if self.goose_logo_path.exists():
            try:
                goose_img = Image(str(self.goose_logo_path), width=1.7 * inch, height=0.43 * inch)
            except Exception as e:
                logger.warning("Goose logo load failed: %s", e)

        header_center = [
            Paragraph(f"<b>{self.plant_info.get('name', 'ANIK DAIRY - BHOPAL')}</b>", title_style),
            Spacer(1, 2),
            Paragraph(
                f"{self.plant_info.get('unit', '10 KL Pasteurizer')} — {report_title}  (Ref: {self.plant_info.get('reference_line', 'PHE-3')})",
                subtitle_style
            ),
            Spacer(1, 2),
            Paragraph(
                f"Logging Period: {start_iso}  →  {end_iso}  |  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                meta_style
            ),
        ]

        header_data = [[anik_img or "", header_center, goose_img or ""]]
        header_table = Table(header_data, colWidths=[1.2 * inch, 8.0 * inch, 1.8 * inch])
        header_table.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN",         (0, 0), (0, 0),   "LEFT"),
            ("ALIGN",         (2, 0), (2, 0),   "RIGHT"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ]))
        elements.append(header_table)
        elements.append(HRFlowable(width="100%", thickness=1.5, color=ANIK_RED))
        elements.append(Spacer(1, 6))

        # ── KPI Summary ───────────────────────────────────────────────────────
        kpis = self._calculate_kpis(raw_records)
        elements.append(self._build_kpi_table(kpis, hdr_style, cell_l, cell_r))
        elements.append(Spacer(1, 8))

        # ── Full Telemetry Table ──────────────────────────────────────────────
        # For PDF: downsample if > 400 rows to keep file manageable
        records = raw_records
        if len(records) > 400:
            step = max(1, len(records) // 400)
            records = raw_records[::step]
            logger.info("PDF downsampled: %d → %d rows (step=%d)", len(raw_records), len(records), step)

        table_hdr_row = [
            Paragraph(f"<b>{lbl}</b>", hdr_style) for lbl, _, _ in PDF_SECTIONS
        ]
        data_rows = [table_hdr_row]

        for r in records:
            has_alarm = (r.get("alarm_main") == 1) or bool(r.get("failures"))
            row_cells = []
            for lbl, field, align in PDF_SECTIONS:
                val_str = _fmt(field, r.get(field))
                sty = alarm_cell if has_alarm and field in ("failures", "alarm_main") else STYLE_MAP[align]
                row_cells.append(Paragraph(val_str, sty))
            data_rows.append(row_cells)

        # Column widths — total must fit in landscape letter minus margins ≈ 10.2 inches
        col_widths = [
            0.85,  # Timestamp
            0.55,  # State
            # Temperatures (9 cols × 0.42)
            0.42, 0.42, 0.42, 0.42, 0.42, 0.42, 0.42, 0.42,
            0.40,  # ΔT
            # Pressures (6 cols × 0.40)
            0.40, 0.40, 0.40, 0.40, 0.40, 0.40,
            # Flow / Control (5 cols)
            0.50, 0.48, 0.40, 0.44, 0.42,
            # Setpoints (5 cols × 0.42)
            0.42, 0.42, 0.42, 0.42, 0.42,
            # Valves (5 cols × 0.35)
            0.35, 0.35, 0.35, 0.35, 0.35,
            # Failures
            0.80,
        ]
        col_widths_pts = [w * inch for w in col_widths]

        style_cmds = [
            ("BACKGROUND",    (0, 0), (-1, 0),  ANIK_NAVY),
            ("GRID",          (0, 0), (-1, -1), 0.3, BORDER_CLR),
            ("TOPPADDING",    (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 2),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 2),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ]

        # Highlight alarm rows red
        for row_idx, r in enumerate(records, 2):
            if r.get("alarm_main") == 1 or bool(r.get("failures")):
                style_cmds.append(("BACKGROUND", (0, row_idx - 1), (-1, row_idx - 1), colors.HexColor("#FEF2F2")))

        data_table = Table(data_rows, colWidths=col_widths_pts, repeatRows=1)
        data_table.setStyle(TableStyle(style_cmds))
        elements.append(data_table)

        doc.build(elements, canvasmaker=NumberedCanvas)
        logger.info("PDF Report generated at: %s", target_path)
        return target_path

    def _build_kpi_table(self, kpis, hdr_style, cell_l, cell_r) -> Table:
        """Compact 3-column KPI summary block."""
        def kv(label, value):
            return [Paragraph(f"<b>{label}:</b>", cell_l), Paragraph(str(value), cell_r)]

        left = [
            kv("Total Milk Processed",      f"{kpis.get('total_milk_kl', 0.0)} KL  ({kpis.get('total_milk_liters', 0):,} L)"),
            kv("Active Production Time",    f"{kpis.get('production_time_min', 0.0)} min"),
            kv("FDV Diversion Events",      f"{kpis.get('divert_count', 0)} events  ({kpis.get('divert_time_min', 0.0)} min)"),
            kv("CIP Duration",              f"{kpis.get('cip_time_min', 0.0)} min"),
        ]
        right = [
            kv("Avg Holding Out Temp TT05", f"{kpis.get('avg_holding_out_c', 0.0)} °C"),
            kv("Avg Holding In Temp TT04",  f"{kpis.get('avg_holding_in_c', 0.0)} °C"),
            kv("Avg Holding Inlet Press PT03", f"{kpis.get('avg_holding_press_bar', 0.0)} Bar"),
            kv("Avg Steam CV",              f"{kpis.get('avg_steam_cv_pct', 0.0)} %"),
        ]
        alarm_pct = kpis.get("alarm_seconds", 0) / max(kpis.get("total_samples", 1), 1) * 100
        bottom = [
            kv("Total Logged Samples",      f"{kpis.get('total_samples', 0):,} records @ 1-second resolution"),
            kv("Master Alarm Active",       f"{kpis.get('alarm_seconds', 0)} s  ({alarm_pct:.1f}% of session)"),
        ]

        def section(rows):
            t = Table([[r[0], r[1]] for r in rows], colWidths=[1.9 * inch, 1.9 * inch])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), ANIK_CREAM),
                ("GRID",       (0, 0), (-1, -1), 0.5, BORDER_CLR),
                ("TOPPADDING",    (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING",   (0, 0), (-1, -1), 5),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
            ]))
            return t

        hdr_cell = Paragraph("<b>EXECUTIVE PROCESS SUMMARY &amp; QUALITY AUDIT METRICS — ALL 30 INSTRUMENTS</b>", hdr_style)
        wrapper = Table(
            [
                [hdr_cell, "", ""],
                [section(left), section(right), section(bottom)],
            ],
            colWidths=[3.8 * inch, 3.8 * inch, 3.8 * inch]
        )
        wrapper.setStyle(TableStyle([
            ("SPAN",       (0, 0), (2, 0)),
            ("BACKGROUND", (0, 0), (2, 0), ANIK_NAVY),
            ("VALIGN",     (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (2, 0),   4),
            ("BOTTOMPADDING", (0, 0), (2, 0), 4),
        ]))
        return wrapper

    def _calculate_kpis(self, all_records: List[Dict]) -> Dict[str, Any]:
        if not all_records:
            return {}

        total_liters = 0.0
        prod_seconds = 0
        divert_count = 0
        in_divert = False
        divert_seconds = 0
        cip_seconds = 0
        alarm_count = 0
        prod_in_temps, prod_out_temps, all_pt03, all_steam = [], [], [], []

        for r in all_records:
            flow  = r.get("feed_flow") or r.get("milk_flow") or 0.0
            fdv1  = r.get("hot_fdv_open") or r.get("fdv1_status") or 0
            fdv2  = r.get("chill_fdv_open") or r.get("fdv2_status") or 0
            cip   = r.get("cip_status") or 0
            alarm = r.get("alarm_main") or 0
            t_in  = r.get("temp_holding_in_tt04") or r.get("holding_in_temp")
            t_out = r.get("temp_holding_out1_tt05") or r.get("holding_out_temp")
            pt03  = r.get("press_holding_in_pt03")
            scv   = r.get("steam_cv")

            if cip   == 1: cip_seconds  += 1
            if alarm == 1: alarm_count  += 1
            if pt03 is not None: all_pt03.append(pt03)
            if scv  is not None: all_steam.append(scv)

            if fdv1 == 1 and fdv2 == 1 and flow > 1000:
                prod_seconds += 1
                total_liters += flow / 3600.0
                in_divert = False
                if t_in  is not None: prod_in_temps.append(t_in)
                if t_out is not None: prod_out_temps.append(t_out)
            elif flow > 1000 and (fdv1 == 0 or fdv2 == 0):
                divert_seconds += 1
                if not in_divert:
                    divert_count += 1
                    in_divert = True

        return {
            "total_samples":        len(all_records),
            "total_milk_liters":    round(total_liters, 1),
            "total_milk_kl":        round(total_liters / 1000.0, 2),
            "production_time_min":  round(prod_seconds  / 60.0, 1),
            "divert_count":         divert_count,
            "divert_time_min":      round(divert_seconds / 60.0, 1),
            "cip_time_min":         round(cip_seconds   / 60.0, 1),
            "alarm_seconds":        alarm_count,
            "avg_holding_in_c":     round(sum(prod_in_temps)  / len(prod_in_temps),  2) if prod_in_temps  else 0.0,
            "avg_holding_out_c":    round(sum(prod_out_temps) / len(prod_out_temps), 2) if prod_out_temps else 0.0,
            "avg_holding_press_bar":round(sum(all_pt03) / len(all_pt03), 3) if all_pt03 else 0.0,
            "avg_steam_cv_pct":     round(sum(all_steam) / len(all_steam), 1) if all_steam else 0.0,
        }
