"""
Audit-Grade PDF Process Report Generator for 10 KL Pasteurizer (Anik Dairy, Bhopal).
Features Anik Dairy logo on top-left, Goose logo on top-right, executive KPI summary table,
and styled process telemetry log table.
"""

import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
import io

from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether, PageBreak
)
from reportlab.pdfgen import canvas

from src.storage.db import DatabaseManager

logger = logging.getLogger("PDFReportGenerator")


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas for dynamic 'Page X of Y' footer."""
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
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        text = f"Anik Dairy 10 KL Pasteurizer Log | Page {self._pageNumber} of {page_count}"
        self.drawRightString(11 * inch - 0.5 * inch, 0.35 * inch, text)
        self.drawString(0.5 * inch, 0.35 * inch, "Confidential - For Quality Assurance & Regulatory Audit Use Only")
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(0.5 * inch, 0.5 * inch, 11 * inch - 0.5 * inch, 0.5 * inch)
        self.restoreState()


class PDFReportGenerator:
    """Generates landscape audit-grade PDF reports with corporate branding."""

    def __init__(self, db_manager: DatabaseManager, output_dir: str = "reports", plant_info: Optional[dict] = None):
        self.db = db_manager
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.plant_info = plant_info or {
            "name": "Anik Dairy - Bhopal",
            "unit": "10 KL Pasteurizer",
            "reference_line": "PHE-3"
        }
        
        # Asset paths
        self.anik_logo_path = Path("docs/assets/anik_logo.png")
        if not self.anik_logo_path.exists():
            self.anik_logo_path = Path("src/dashboard/static/img/anik_logo.png")
            
        self.goose_logo_path = Path("docs/assets/goose_logo.png")
        if not self.goose_logo_path.exists():
            self.goose_logo_path = Path("src/dashboard/static/img/goose_logo.png")

    def generate_pdf(
        self,
        start_iso: str,
        end_iso: str,
        report_title: str = "Shift Process Report",
        sample_step: int = 1
    ) -> Optional[Path]:
        """
        Generate a PDF report for the given time range.
        
        Args:
            start_iso: Start timestamp in ISO format
            end_iso: End timestamp in ISO format
            report_title: Header title
            sample_step: Downsampling interval in seconds (default 1)
            
        Returns:
            Path to generated .pdf file or None if no data
        """
        logger.info("Generating PDF report '%s' from %s to %s...", report_title, start_iso, end_iso)
        raw_records = self.db.get_records_between(start_iso, end_iso)

        if not raw_records:
            logger.warning("No records found in database for PDF between %s and %s", start_iso, end_iso)
            return None

        # Build output path
        start_dt = datetime.fromisoformat(start_iso.replace("Z", ""))
        date_str = start_dt.strftime("%Y%m%d_%H%M")
        clean_title = report_title.replace(" ", "_").lower()
        filename = f"{clean_title}_{date_str}.pdf"
        target_path = self.output_dir / filename

        # Create PDF document in landscape for rich tabular data
        doc = SimpleDocTemplate(
            str(target_path),
            pagesize=landscape(letter),
            leftMargin=0.5 * inch,
            rightMargin=0.5 * inch,
            topMargin=0.4 * inch,
            bottomMargin=0.6 * inch
        )

        elements = []
        styles = getSampleStyleSheet()

        # Custom paragraph styles
        title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=colors.HexColor("#0F172A"),
            alignment=1  # Centered
        )
        subtitle_style = ParagraphStyle(
            "DocSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor("#475569"),
            alignment=1
        )
        meta_style = ParagraphStyle(
            "DocMeta",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#64748B"),
            alignment=1
        )
        table_hdr_style = ParagraphStyle(
            "TblHdr",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.white,
            alignment=1
        )
        table_cell_style = ParagraphStyle(
            "TblCell",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=9.5,
            textColor=colors.HexColor("#1E293B")
        )
        table_cell_center = ParagraphStyle(
            "TblCellCenter",
            parent=table_cell_style,
            alignment=1
        )
        table_cell_right = ParagraphStyle(
            "TblCellRight",
            parent=table_cell_style,
            alignment=2
        )

        # 1. Header with Both Logos
        # Logo 1: Anik Logo (Left)
        anik_img = None
        if self.anik_logo_path.exists():
            anik_img = Image(str(self.anik_logo_path), width=1.1 * inch, height=0.6 * inch)
            anik_img.hAlign = "LEFT"

        # Logo 2: Goose Logo (Right)
        goose_img = None
        if self.goose_logo_path.exists():
            goose_img = Image(str(self.goose_logo_path), width=1.9 * inch, height=0.48 * inch)
            goose_img.hAlign = "RIGHT"

        header_center = [
            Paragraph(f"<b>{self.plant_info.get('name', 'ANIK DAIRY - BHOPAL')}</b>", title_style),
            Spacer(1, 2),
            Paragraph(f"{self.plant_info.get('unit', '10 KL Pasteurizer')} - {report_title} (Ref: {self.plant_info.get('reference_line', 'PHE-3')})", subtitle_style),
            Spacer(1, 2),
            Paragraph(f"Logging Period: {start_iso} to {end_iso} | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", meta_style)
        ]

        header_data = [[anik_img or "", header_center, goose_img or ""]]
        header_table = Table(header_data, colWidths=[1.3 * inch, 7.4 * inch, 2.1 * inch])
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (0, 0), "LEFT"),
            ("ALIGN", (2, 0), (2, 0), "RIGHT"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 8))

        # 2. Compute Summary KPIs
        kpis = self._calculate_kpis(raw_records)

        # 3. KPI Summary Table
        kpi_hdr = Paragraph("<b>EXECUTIVE PROCESS SUMMARY & QUALITY AUDIT METRICS</b>", table_hdr_style)
        kpi_table_data = [
            [kpi_hdr, "", "", "", "", ""],
            [
                Paragraph("<b>Total Milk Processed:</b>", table_cell_style),
                Paragraph(f"<b>{kpis.get('total_milk_kl', 0.0)} KL</b> ({kpis.get('total_milk_liters', 0):,} L)", table_cell_style),
                Paragraph("<b>Avg Holding In Temp:</b>", table_cell_style),
                Paragraph(f"{kpis.get('avg_holding_in_c', 0.0)} °C (Std: 81.0-81.5°C)", table_cell_style),
                Paragraph("<b>Active Production Time:</b>", table_cell_style),
                Paragraph(f"{kpis.get('production_time_min', 0.0)} min", table_cell_style),
            ],
            [
                Paragraph("<b>Diversion Events:</b>", table_cell_style),
                Paragraph(f"{kpis.get('divert_count', 0)} ({kpis.get('divert_time_min', 0.0)} min total)", table_cell_style),
                Paragraph("<b>Avg Holding Out Temp:</b>", table_cell_style),
                Paragraph(f"{kpis.get('avg_holding_out_c', 0.0)} °C", table_cell_style),
                Paragraph("<b>CIP Active Duration:</b>", table_cell_style),
                Paragraph(f"{kpis.get('cip_time_min', 0.0)} min", table_cell_style),
            ]
        ]
        kpi_table = Table(kpi_table_data, colWidths=[1.8 * inch, 1.8 * inch, 1.8 * inch, 1.8 * inch, 1.8 * inch, 1.8 * inch])
        kpi_table.setStyle(TableStyle([
            ("SPAN", (0, 0), (5, 0)),
            ("BACKGROUND", (0, 0), (5, 0), colors.HexColor("#0F172A")),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F8FAFC")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(kpi_table)
        elements.append(Spacer(1, 10))

        # 4. Telemetric Process Data Table
        # For PDF readability and performance, downsample if records > 250
        records = raw_records
        if len(records) > 250:
            step = len(records) // 250
            records = raw_records[::step]

        table_headers = [
            Paragraph("<b>Timestamp</b>", table_hdr_style),
            Paragraph("<b>Product</b>", table_hdr_style),
            Paragraph("<b>Milk Flow<br/>(L/hr)</b>", table_hdr_style),
            Paragraph("<b>Hold In<br/>(°C)</b>", table_hdr_style),
            Paragraph("<b>Hold Out<br/>(°C)</b>", table_hdr_style),
            Paragraph("<b>FDV-1</b>", table_hdr_style),
            Paragraph("<b>FDV-1 Reason</b>", table_hdr_style),
            Paragraph("<b>FDV-2</b>", table_hdr_style),
            Paragraph("<b>FDV-2 Reason</b>", table_hdr_style),
            Paragraph("<b>CIP</b>", table_hdr_style),
            Paragraph("<b>Status Description</b>", table_hdr_style),
        ]

        data_rows = [table_headers]
        for idx, r in enumerate(records):
            t_str = r.get("timestamp", "").replace("T", " ")[:19]
            prod = r.get("product") or "--"
            flow = f"{r.get('milk_flow', 0):,.1f}" if r.get("milk_flow") is not None else "--"
            t_in = f"{r.get('holding_in_temp', 0):.2f}" if r.get("holding_in_temp") is not None else "--"
            t_out = f"{r.get('holding_out_temp', 0):.2f}" if r.get("holding_out_temp") is not None else "--"
            fdv1 = "FWD" if r.get("fdv1_status") == 1 else "DIVERT"
            fdv1_r = r.get("fdv1_reason") or "All Ok"
            fdv2 = "FWD" if r.get("fdv2_status") == 1 else "DIVERT"
            fdv2_r = r.get("fdv2_reason") or "All Ok"
            cip = "ACTIVE" if r.get("cip_status") == 1 else "IDLE"
            st = r.get("status") or "--"

            row = [
                Paragraph(t_str, table_cell_center),
                Paragraph(prod, table_cell_style),
                Paragraph(flow, table_cell_right),
                Paragraph(t_in, table_cell_right),
                Paragraph(t_out, table_cell_right),
                Paragraph(fdv1, table_cell_center),
                Paragraph(fdv1_r, table_cell_style),
                Paragraph(fdv2, table_cell_center),
                Paragraph(fdv2_r, table_cell_style),
                Paragraph(cip, table_cell_center),
                Paragraph(st, table_cell_style),
            ]
            data_rows.append(row)

        data_col_widths = [
            1.25 * inch,  # Timestamp
            1.10 * inch,  # Product
            0.85 * inch,  # Flow
            0.65 * inch,  # Hold In
            0.65 * inch,  # Hold Out
            0.60 * inch,  # FDV1
            1.05 * inch,  # FDV1 Reason
            0.60 * inch,  # FDV2
            1.05 * inch,  # FDV2 Reason
            0.65 * inch,  # CIP
            2.35 * inch,  # Status
        ]

        data_table = Table(data_rows, colWidths=data_col_widths, repeatRows=1)
        data_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ]))
        elements.append(data_table)

        # Build document with custom canvas
        doc.build(elements, canvasmaker=NumberedCanvas)
        logger.info("PDF Report generated at: %s", target_path)
        return target_path

    def _calculate_kpis(self, all_records: List[Dict]) -> Dict[str, Any]:
        """Compute summary statistics."""
        if not all_records:
            return {}

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
            "total_samples": len(all_records),
            "total_milk_liters": round(total_liters, 1),
            "total_milk_kl": round(total_liters / 1000.0, 2),
            "production_time_min": round(prod_seconds / 60.0, 1),
            "divert_count": divert_count,
            "divert_time_min": round(divert_seconds / 60.0, 1),
            "cip_time_min": round(cip_seconds / 60.0, 1),
            "avg_holding_in_c": round(avg_in, 2),
            "avg_holding_out_c": round(avg_out, 2),
        }
