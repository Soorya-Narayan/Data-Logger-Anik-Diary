"""
Audit-Grade PDF Process Report Generator for 10 KL Pasteurizer (Anik Dairy, Bhopal).
Structured for regulatory food safety compliance (FSSAI) and dairy plant management.

Features:
- Section 1: Thermal Pasteurization & Critical Control Point (CCP) Audit Log (TT01–TT16, Delta-T, Flow, Totalizer, Valves, Alarms)
- Section 2: Plant Hydraulics, Pressures, Energy Setpoints & Auxiliary Log (PT01–PT06, Steam CV, Deodoriser Level, Regen Eff, SP01–SP05, CIP, Failures)
- Exact 10.2-inch landscape table bounds (zero clipping, zero horizontal overflow)
- Highlighted TT06 Critical Control Point (CCP) legal pasteurization temperatures
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
    PageBreak, HRFlowable
)
from reportlab.pdfgen import canvas

from src.storage.db import DatabaseManager

logger = logging.getLogger("PDFReportGenerator")

# ── Anik Dairy Brand Colours ──────────────────────────────────────────────────
ANIK_RED   = colors.HexColor("#D7262D")
ANIK_NAVY  = colors.HexColor("#152238")
ANIK_GOLD  = colors.HexColor("#C28E3A")
ANIK_GREEN = colors.HexColor("#15803D")
ANIK_CREAM = colors.HexColor("#FAF7F2")
SLATE      = colors.HexColor("#475569")
LIGHT_GREY = colors.HexColor("#F8FAFC")
BORDER_CLR = colors.HexColor("#CBD5E1")
WHITE      = colors.white
BLACK      = colors.HexColor("#0F172A")
CCP_BG     = colors.HexColor("#FEF3C7")  # Warm soft gold highlight for TT06 CCP

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ── SECTION 1: Thermal Pasteurization & CCP Process Telemetry (18 Columns = 734 pt) ──
SECTION_1_COLS = [
    # (Header Label, DB Field, Alignment, Width in Points)
    ("Date & Time",             "timestamp",                "C", 46),
    ("State",                   "product",                  "C", 44),
    ("TT-01<br/>In (°C)",       "temp_tt01",                "R", 36),
    ("TT-02<br/>R1 (°C)",       "temp_tt02",                "R", 36),
    ("TT-03<br/>R2 (°C)",       "temp_tt03",                "R", 36),
    ("TT-05<br/>HoldIn",        "temp_tt05",                "R", 36),
    ("TT-06<br/>CCP (°C)",      "temp_tt06",                "R", 44),  # Legal Pasteurization Temp
    ("TT-08<br/>Out2",          "temp_tt08",                "R", 36),
    ("TT-11<br/>R.Out",         "temp_tt11",                "R", 36),
    ("TT-12<br/>P.Out",         "temp_tt12",                "R", 36),
    ("TT-15<br/>Ch.In",         "temp_tt15",                "R", 36),
    ("TT-16<br/>Ch.Out",        "temp_tt16",                "R", 36),
    ("ΔT<br/>(°C)",             "delta_t",                  "R", 34),
    ("Feed Flow<br/>(L/H)",     "feed_flow",                "R", 44),
    ("Product<br/>Tot (L)",     "product_tot",              "R", 48),
    ("HOT<br/>FDV",             "hot_fdv_open",             "C", 34),
    ("CHILL<br/>FDV",           "chill_fdv_open",           "C", 34),
    ("Safety<br/>Status",       "failures",                 "C", 58),
]

# ── SECTION 2: Hydraulics, Pressures, Energy Setpoints & Auxiliaries (19 Columns = 720 pt) ──
SECTION_2_COLS = [
    ("Date & Time",             "timestamp",                "C", 44),
    ("PT-01<br/>Raw (Bar)",     "press_raw_milk_pt01",      "R", 38),
    ("PT-02<br/>R2 (Bar)",      "press_regen_r2_pt02",      "R", 38),
    ("PT-03<br/>Hold (Bar)",    "press_holding_in_pt03",    "R", 38),
    ("PT-04<br/>Chill (Bar)",   "press_chilled_milk_pt04",  "R", 38),
    ("PT-05<br/>Hot (Bar)",     "press_hot_water_pt05",     "R", 38),
    ("PT-06<br/>Chil (Bar)",    "press_chilling_pt06",      "R", 38),
    ("Steam<br/>CV (%)",        "steam_cv",                 "R", 36),
    ("Deodor<br/>Lvl (%)",      "deodoriser_level",         "R", 36),
    ("Regen<br/>Eff (%)",       "regen_efficiency",         "R", 36),
    ("SP Heat<br/>(°C)",        "sp_heating_temp",          "R", 38),
    ("SP Div<br/>(°C)",         "sp_chill_fdv_diversion",   "R", 38),
    ("SP Hys<br/>(°C)",         "sp_heating_fdv_hys",       "R", 38),
    ("SP Ch.P<br/>(Bar)",       "sp_chilling_pressure",     "R", 38),
    ("SP Rg.P<br/>(Bar)",       "sp_regen_r1_pressure",     "R", 38),
    ("Force<br/>Circ",          "force_circulation",        "C", 32),
    ("Force<br/>Fwd",           "force_forward",            "C", 32),
    ("CIP<br/>Mode",            "cip_status",               "C", 32),
    ("Active Failures /<br/>Diagnostics", "failures",       "C", 54),
]


def _format_val(field: str, val) -> str:
    """Format a single DB value with precision suitable for regulatory review."""
    if val is None:
        return "--"

    # Valves & Booleans
    if field in ("hot_fdv_open", "chill_fdv_open", "fdv1_status", "fdv2_status"):
        return "FWD" if val == 1 else "DIV"
    if field in ("force_circulation", "force_forward"):
        return "ON" if val == 1 else "OFF"
    if field == "cip_status":
        return "ACT" if val == 1 else "IDLE"

    # Pressures (3 decimals)
    if field.startswith("press_"):
        try:
            return f"{float(val):.3f}"
        except Exception:
            return str(val)

    # Setpoint pressures
    if field in ("sp_chilling_pressure", "sp_regen_r1_pressure"):
        try:
            return f"{float(val):.2f}"
        except Exception:
            return str(val)

    # Flows and Totals
    if field in ("feed_flow", "milk_flow"):
        try:
            return f"{float(val):,.0f}"
        except Exception:
            return str(val)
    if field == "product_tot":
        try:
            return f"{float(val):,.0f}"
        except Exception:
            return str(val)

    # Temperatures & Percentages
    if field.startswith("temp_") or field in ("delta_t", "steam_cv", "deodoriser_level", "regen_efficiency", "sp_heating_temp", "sp_chill_fdv_diversion", "sp_heating_fdv_hys"):
        try:
            return f"{float(val):.2f}"
        except Exception:
            return str(val)

    # Timestamp: show compact time HH:MM:SS
    if field == "timestamp":
        s = str(val)
        return s.split("T")[-1][:8] if "T" in s else s[:8]

    # Process State
    if field == "product":
        s = str(val).upper()
        if "TONED" in s:
            return "TONED"
        if "STANDARDIZED" in s:
            return "STND"
        if "DOUBLE" in s:
            return "DTM"
        if "CIP" in s:
            return "CIP"
        return s[:8] if s else "PROD"

    # Alarms / Failures
    if field == "failures":
        s = str(val)
        return "NORMAL" if not s or s == "NORMAL" else s[:12]

    return str(val)


# ── Page Footer Canvas ────────────────────────────────────────────────────────
class NumberedCanvas(canvas.Canvas):
    """Dynamic two-pass canvas that writes exact total page counts and audit footers."""
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
        self.drawRightString(11 * inch - 0.4 * inch, 0.30 * inch, text)
        self.drawString(0.4 * inch, 0.30 * inch, "Confidential — Quality Assurance & Regulatory Audit Use Only")
        self.setStrokeColor(BORDER_CLR)
        self.setLineWidth(0.5)
        self.line(0.4 * inch, 0.44 * inch, 11 * inch - 0.4 * inch, 0.44 * inch)
        self.restoreState()


# ── Main Generator ─────────────────────────────────────────────────────────────
class PDFReportGenerator:
    """Generates audit-grade PDF reports covering all SCADA instruments with zero clipping."""

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
        logger.info("Generating Audit PDF '%s' from %s to %s...", report_title, start_iso, end_iso)
        raw_records = self.db.get_records_between(start_iso, end_iso)

        if not raw_records:
            logger.warning("No records found for PDF between %s and %s", start_iso, end_iso)
            return None

        # Filter to ensure uniform 3-second logging intervals
        from src.reports.scheduler import filter_records_interval
        raw_records = filter_records_interval(raw_records, interval_sec=3.0)

        # For PDF printable readability: sample up to 300 rows across time range
        records = raw_records
        if len(records) > 300:
            step = max(1, len(records) // 300)
            records = raw_records[::step]
            logger.info("PDF telemetry sampled: %d → %d rows (step=%d)", len(raw_records), len(records), step)

        start_dt = datetime.fromisoformat(start_iso.replace("Z", ""))
        date_str = start_dt.strftime("%Y%m%d_%H%M")
        clean_title = report_title.replace(" ", "_").lower()
        filename = f"{clean_title}_{date_str}.pdf"
        target_path = self.output_dir / filename

        # Letter Landscape: 11.0 x 8.5 inches (792 x 612 pt)
        # Margins: 0.4" left/right -> Printable Width = 10.2 inches (734.4 pt)
        doc = SimpleDocTemplate(
            str(target_path),
            pagesize=landscape(letter),
            leftMargin=0.4 * inch,
            rightMargin=0.4 * inch,
            topMargin=0.35 * inch,
            bottomMargin=0.55 * inch
        )

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle("DocTitle", parent=styles["Normal"],
            fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=ANIK_NAVY, alignment=1)
        subtitle_style = ParagraphStyle("DocSub", parent=styles["Normal"],
            fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=SLATE, alignment=1)
        meta_style = ParagraphStyle("DocMeta", parent=styles["Normal"],
            fontName="Helvetica", fontSize=7.5, leading=9, textColor=SLATE, alignment=1)

        hdr_style = ParagraphStyle("TblHdr", parent=styles["Normal"],
            fontName="Helvetica-Bold", fontSize=6.5, leading=8, textColor=WHITE, alignment=1)
        hdr_ccp = ParagraphStyle("HdrCCP", parent=styles["Normal"],
            fontName="Helvetica-Bold", fontSize=6.5, leading=8, textColor=colors.HexColor("#FEF08A"), alignment=1)

        cell_c = ParagraphStyle("CellC", parent=styles["Normal"],
            fontName="Helvetica", fontSize=6.5, leading=8, textColor=BLACK, alignment=1)
        cell_r = ParagraphStyle("CellR", parent=styles["Normal"],
            fontName="Helvetica", fontSize=6.5, leading=8, textColor=BLACK, alignment=2)
        cell_l = ParagraphStyle("CellL", parent=styles["Normal"],
            fontName="Helvetica", fontSize=6.5, leading=8, textColor=BLACK, alignment=0)
        cell_ccp = ParagraphStyle("CellCCP", parent=styles["Normal"],
            fontName="Helvetica-Bold", fontSize=6.5, leading=8, textColor=ANIK_RED, alignment=2)
        cell_fwd = ParagraphStyle("CellFWD", parent=styles["Normal"],
            fontName="Helvetica-Bold", fontSize=6.5, leading=8, textColor=ANIK_GREEN, alignment=1)
        cell_div = ParagraphStyle("CellDIV", parent=styles["Normal"],
            fontName="Helvetica-Bold", fontSize=6.5, leading=8, textColor=ANIK_RED, alignment=1)
        cell_alm = ParagraphStyle("CellALM", parent=styles["Normal"],
            fontName="Helvetica-Bold", fontSize=6.5, leading=8, textColor=ANIK_RED, alignment=1)

        STYLE_MAP = {"C": cell_c, "R": cell_r, "L": cell_l}

        elements = []

        # ── 1. Document Header (Exact 10.2 inches) ────────────────────────────
        elements.append(self._build_header(report_title, start_iso, end_iso, title_style, subtitle_style, meta_style))
        elements.append(HRFlowable(width="100%", thickness=1.5, color=ANIK_RED, hAlign="LEFT"))
        elements.append(Spacer(1, 4))

        # ── 2. Executive KPI & Quality Audit Metrics (Exact 10.2 inches) ───────
        kpis = self._calculate_kpis(raw_records)
        elements.append(self._build_kpi_table(kpis, hdr_style, cell_l, cell_r))
        elements.append(Spacer(1, 6))

        # ── 3. Section 1: Thermal Pasteurization & CCP Audit Log ──────────────
        sec1_banner = Table([[
            Paragraph("<b>SECTION 1: THERMAL PASTEURIZATION & CRITICAL CONTROL POINT (CCP) AUDIT LOG</b>", hdr_style)
        ]], colWidths=[10.2 * inch], hAlign="LEFT")
        sec1_banner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1E293B")),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ]))
        elements.append(sec1_banner)

        # Build Section 1 Table
        col_w1 = [w for _, _, _, w in SECTION_1_COLS]
        h1_row = [
            Paragraph(f"<b>{lbl}</b>", hdr_ccp if field == "temp_tt06" else hdr_style)
            for lbl, field, _, _ in SECTION_1_COLS
        ]
        t1_rows = [h1_row]

        for r in records:
            row_cells = []
            for lbl, field, align, _ in SECTION_1_COLS:
                val_str = _format_val(field, r.get(field))
                if field == "temp_tt06":
                    sty = cell_ccp
                elif field in ("hot_fdv_open", "chill_fdv_open"):
                    sty = cell_fwd if val_str == "FWD" else cell_div
                elif field == "failures" and val_str != "NORMAL":
                    sty = cell_alm
                else:
                    sty = STYLE_MAP[align]
                row_cells.append(Paragraph(val_str, sty))
            t1_rows.append(row_cells)

        t1 = Table(t1_rows, colWidths=col_w1, hAlign="LEFT", repeatRows=1)
        t1.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  ANIK_NAVY),
            ("GRID",          (0, 0), (-1, -1), 0.3, BORDER_CLR),
            ("TOPPADDING",    (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 1.5),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 1.5),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND",    (6, 0), (6, -1),  CCP_BG),  # Highlight Legal TT06 CCP column
        ]))
        elements.append(t1)

        # ── 4. Section 2: Plant Hydraulics, Pressures & Auxiliaries ───────────
        elements.append(PageBreak())

        # Header continuation on Page 2
        elements.append(self._build_header(report_title, start_iso, end_iso, title_style, subtitle_style, meta_style))
        elements.append(HRFlowable(width="100%", thickness=1.5, color=ANIK_RED, hAlign="LEFT"))
        elements.append(Spacer(1, 6))

        sec2_banner = Table([[
            Paragraph("<b>SECTION 2: PLANT HYDRAULICS, PRESSURES, ENERGY SETPOINTS & AUXILIARY SYSTEM LOG</b>", hdr_style)
        ]], colWidths=[10.2 * inch], hAlign="LEFT")
        sec2_banner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1E293B")),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ]))
        elements.append(sec2_banner)

        # Build Section 2 Table
        col_w2 = [w for _, _, _, w in SECTION_2_COLS]
        h2_row = [
            Paragraph(f"<b>{lbl}</b>", hdr_style) for lbl, _, _, _ in SECTION_2_COLS
        ]
        t2_rows = [h2_row]

        for r in records:
            row_cells = []
            for lbl, field, align, _ in SECTION_2_COLS:
                val_str = _format_val(field, r.get(field))
                if field == "failures" and val_str != "NORMAL":
                    sty = cell_alm
                else:
                    sty = STYLE_MAP[align]
                row_cells.append(Paragraph(val_str, sty))
            t2_rows.append(row_cells)

        t2 = Table(t2_rows, colWidths=col_w2, hAlign="LEFT", repeatRows=1)
        t2.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  ANIK_NAVY),
            ("GRID",          (0, 0), (-1, -1), 0.3, BORDER_CLR),
            ("TOPPADDING",    (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 1.5),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 1.5),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(t2)

        # Build PDF with dynamic 2-pass page numbering
        doc.build(elements, canvasmaker=NumberedCanvas)
        logger.info("Audit PDF Report generated successfully: %s", target_path)
        return target_path

    def _build_header(self, report_title, start_iso, end_iso, title_style, subtitle_style, meta_style) -> Table:
        """Header with Anik Dairy & Goose logos fitted precisely across 10.2 inches."""
        anik_img = None
        if self.anik_logo_path.exists():
            try:
                anik_img = Image(str(self.anik_logo_path), width=1.0 * inch, height=0.55 * inch)
            except Exception as e:
                logger.warning("Anik logo load failed: %s", e)

        goose_img = None
        if self.goose_logo_path.exists():
            try:
                goose_img = Image(str(self.goose_logo_path), width=1.5 * inch, height=0.38 * inch)
            except Exception as e:
                logger.warning("Goose logo load failed: %s", e)

        center_content = [
            Paragraph(f"<b>{self.plant_info.get('name', 'ANIK DAIRY - BHOPAL').upper()}</b>", title_style),
            Spacer(1, 1),
            Paragraph(
                f"{self.plant_info.get('unit', '10 KL Pasteurizer')} — {report_title} (Ref: {self.plant_info.get('reference_line', 'PHE-3')})",
                subtitle_style
            ),
            Spacer(1, 1),
            Paragraph(
                f"Logging Period: {start_iso} → {end_iso}  |  Resolution: 3-Second Cadence  |  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                meta_style
            ),
        ]

        # Total width = 1.2 + 7.4 + 1.6 = 10.2 inches
        hdr_table = Table([[anik_img or "", center_content, goose_img or ""]], colWidths=[1.2 * inch, 7.4 * inch, 1.6 * inch], hAlign="LEFT")
        hdr_table.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN",         (0, 0), (0, 0),   "LEFT"),
            ("ALIGN",         (2, 0), (2, 0),   "RIGHT"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ]))
        return hdr_table

    def _build_kpi_table(self, kpis, hdr_style, cell_l, cell_r) -> Table:
        """Compact 3-column KPI summary block fitted exactly to 10.2 inches."""
        def kv(label, value):
            return [Paragraph(f"<b>{label}:</b>", cell_l), Paragraph(str(value), cell_r)]

        compliance_rate = kpis.get("compliance_pct", 99.8)
        status_color = "#15803D" if compliance_rate >= 95.0 and kpis.get("divert_count", 0) <= 3 else "#D7262D"
        verdict = f'<font color="{status_color}"><b>PASS — APPROVED</b></font>' if compliance_rate >= 95.0 else f'<font color="{status_color}"><b>DIVERT DETECTED</b></font>'

        col1 = [
            kv("Total Milk Processed",   f"{kpis.get('total_milk_kl', 0.0)} KL ({kpis.get('total_milk_liters', 0):,} L)"),
            kv("Active Production Time", f"{kpis.get('production_time_min', 0.0)} min"),
            kv("FDV Diversion Events",   f"{kpis.get('divert_count', 0)} events ({kpis.get('divert_time_min', 0.0)} min)"),
            kv("CIP Sequence Duration",  f"{kpis.get('cip_time_min', 0.0)} min"),
        ]
        col2 = [
            kv("Avg Holding Out (TT06 CCP)", f"{kpis.get('avg_holding_out_c', 0.0)} °C"),
            kv("Avg Holding In (TT05)",      f"{kpis.get('avg_holding_in_c', 0.0)} °C"),
            kv("Avg Holding Press (PT03)",   f"{kpis.get('avg_holding_press_bar', 0.0)} Bar"),
            kv("Avg Steam CV Opening",       f"{kpis.get('avg_steam_cv_pct', 0.0)} %"),
        ]
        col3 = [
            kv("Total Logged Samples",       f"{kpis.get('total_samples', 0):,} records @ 3-sec"),
            kv("Temperature Compliance",     f"{compliance_rate:.1f}% (Target ≥72°C)"),
            kv("Master Alarm Active",        f"{kpis.get('alarm_seconds', 0)} s ({kpis.get('alarm_pct', 0.0):.1f}% session)"),
            kv("FSSAI Audit Verdict",        verdict),
        ]

        def make_section(rows):
            t = Table([[r[0], r[1]] for r in rows], colWidths=[1.8 * inch, 1.6 * inch])
            t.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), ANIK_CREAM),
                ("GRID",          (0, 0), (-1, -1), 0.5, BORDER_CLR),
                ("TOPPADDING",    (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING",   (0, 0), (-1, -1), 4),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
            ]))
            return t

        hdr_cell = Paragraph("<b>EXECUTIVE PROCESS SUMMARY &amp; QUALITY AUDIT METRICS — 10 KL PASTEURIZER PHE-3</b>", hdr_style)
        # Total width = 3.4 * 3 = 10.2 inches
        wrapper = Table(
            [
                [hdr_cell, "", ""],
                [make_section(col1), make_section(col2), make_section(col3)],
            ],
            colWidths=[3.4 * inch, 3.4 * inch, 3.4 * inch],
            hAlign="LEFT"
        )
        wrapper.setStyle(TableStyle([
            ("SPAN",          (0, 0), (2, 0)),
            ("BACKGROUND",    (0, 0), (2, 0), ANIK_NAVY),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",    (0, 0), (2, 0),   3),
            ("BOTTOMPADDING", (0, 0), (2, 0),   3),
        ]))
        return wrapper

    def _calculate_kpis(self, all_records: List[Dict]) -> Dict[str, Any]:
        """Compute key production and compliance indicators from telemetry records."""
        if not all_records:
            return {}

        total_liters = 0.0
        prod_samples = 0
        divert_count = 0
        in_divert = False
        divert_samples = 0
        cip_samples = 0
        alarm_samples = 0
        prod_in_temps, prod_out_temps, all_pt03, all_steam = [], [], [], []

        for r in all_records:
            flow  = r.get("feed_flow") or r.get("milk_flow") or 0.0
            fdv1  = r.get("hot_fdv_open") or r.get("fdv1_status") or 0
            fdv2  = r.get("chill_fdv_open") or r.get("fdv2_status") or 0
            cip   = r.get("cip_status") or 0
            alarm = r.get("alarm_main") or 0
            t_in  = r.get("temp_tt05") or r.get("temp_holding_in_tt04") or r.get("holding_in_temp")
            t_out = r.get("temp_tt06") or r.get("temp_holding_out1_tt05") or r.get("holding_out_temp")
            pt03  = r.get("press_holding_in_pt03")
            scv   = r.get("steam_cv")

            if cip == 1:
                cip_samples += 1
            if alarm == 1:
                alarm_samples += 1
            if pt03 is not None:
                all_pt03.append(float(pt03))
            if scv is not None:
                all_steam.append(float(scv))

            if fdv1 == 1 and fdv2 == 1 and flow > 500:
                prod_samples += 1
                total_liters += (flow / 3600.0) * 3.0  # 3-second sample interval
                in_divert = False
                if t_in is not None:
                    prod_in_temps.append(float(t_in))
                if t_out is not None:
                    prod_out_temps.append(float(t_out))
            elif flow > 500 and (fdv1 == 0 or fdv2 == 0):
                divert_samples += 1
                if not in_divert:
                    divert_count += 1
                    in_divert = True

        total_samples = len(all_records)
        safe_temps = [t for t in prod_out_temps if t >= 72.0]
        compliance_pct = (len(safe_temps) / len(prod_out_temps) * 100.0) if prod_out_temps else 100.0
        alarm_pct = (alarm_samples / max(total_samples, 1)) * 100.0

        return {
            "total_samples":        total_samples,
            "total_milk_liters":    round(total_liters, 1),
            "total_milk_kl":        round(total_liters / 1000.0, 2),
            "production_time_min":  round((prod_samples * 3.0) / 60.0, 1),
            "divert_count":         divert_count,
            "divert_time_min":      round((divert_samples * 3.0) / 60.0, 1),
            "cip_time_min":         round((cip_samples * 3.0) / 60.0, 1),
            "alarm_seconds":        alarm_samples * 3,
            "alarm_pct":            round(alarm_pct, 1),
            "compliance_pct":       round(compliance_pct, 1),
            "avg_holding_in_c":     round(sum(prod_in_temps)  / len(prod_in_temps),  2) if prod_in_temps  else 0.0,
            "avg_holding_out_c":    round(sum(prod_out_temps) / len(prod_out_temps), 2) if prod_out_temps else 0.0,
            "avg_holding_press_bar":round(sum(all_pt03) / len(all_pt03), 3) if all_pt03 else 0.0,
            "avg_steam_cv_pct":     round(sum(all_steam) / len(all_steam), 1) if all_steam else 0.0,
        }
