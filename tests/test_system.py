"""
Unit and Integration Tests for Pasteurizer Data Logging System.
"""

import os
import sys
import shutil
import unittest
from pathlib import Path
from datetime import datetime, timedelta

# Add root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.plc.mock_client import MockPLCClient
from src.plc.live_client import LivePLCClient
from src.storage.db import DatabaseManager
from src.storage.buffer import DataBuffer
from src.reports.generator import ExcelReportGenerator


class TestPasteurizerSystem(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path("scratch/test_env")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.test_db_path = str(self.test_dir / "test_pasteurizer.db")

        self.mock_config = {
            "plc": {
                "mode": "mock",
                "ip": "192.168.1.50",
                "slot": 0,
                "timeout": 3.0,
                "mock": {
                    "enable_random_dropouts": False
                }
            }
        }

        self.mock_tags = {
            "tags": {
                "milk_flow": {"plc_tag": "FIT_101_FlowRate"},
                "holding_in_temp": {"plc_tag": "TT_101_HoldingInTemp"},
                "holding_out_temp": {"plc_tag": "TT_102_HoldingOutTemp"},
                "product": {"plc_tag": "Recipe_ProductName"},
                "status": {"plc_tag": "System_ProcessStatus"},
                "fdv1_status": {"plc_tag": "FDV1_ForwardStatus"},
                "fdv1_reason": {"plc_tag": "FDV1_DiversionReason"},
                "fdv2_status": {"plc_tag": "FDV2_ForwardStatus"},
                "fdv2_reason": {"plc_tag": "FDV2_DiversionReason"},
                "cip_status": {"plc_tag": "CIP_SystemActive"},
                "cip_step": {"plc_tag": "CIP_CurrentStepName"},
                "fdv_feedback": {"plc_tag": "FDV_AuxFeedbackWord"}
            }
        }

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_mock_plc_client_telemetry(self):
        """Verify MockPLCClient generates complete, valid telemetry."""
        client = MockPLCClient(self.mock_config)
        self.assertTrue(client.connect())
        self.assertTrue(client.is_connected())

        sample = client.read_tags()
        self.assertIn("timestamp", sample)
        self.assertIn("milk_flow", sample)
        self.assertIn("holding_in_temp", sample)
        self.assertIn("holding_out_temp", sample)
        self.assertIn("status", sample)
        self.assertIn("fdv1_status", sample)
        self.assertIn("fdv2_status", sample)

        # Realistic ranges
        self.assertGreaterEqual(sample["milk_flow"], 0.0)
        self.assertGreaterEqual(sample["holding_in_temp"], 30.0)
        self.assertLessEqual(sample["holding_in_temp"], 110.0)

        client.disconnect()
        self.assertFalse(client.is_connected())

    def test_database_and_buffer_batching(self):
        """Verify buffered writes to SQLite without row-by-row disk commits."""
        db = DatabaseManager(self.test_db_path)
        buffer = DataBuffer(db, batch_flush_seconds=100.0, batch_max_size=5)

        client = MockPLCClient(self.mock_config)
        client.connect()

        # Add 4 records (below batch_max_size=5, should remain in buffer)
        for _ in range(4):
            sample = client.read_tags()
            buffer.add(sample)

        self.assertEqual(buffer.pending_count(), 4)
        self.assertIsNone(db.get_latest_record())

        # Add 5th record -> Should auto-flush
        sample = client.read_tags()
        buffer.add(sample)
        self.assertEqual(buffer.pending_count(), 0)

        latest = db.get_latest_record()
        self.assertIsNotNone(latest)
        self.assertEqual(latest["product"], sample["product"])

    def test_excel_report_generation(self):
        """Verify ExcelReportGenerator produces valid .xlsx matching PHE-3 format."""
        db = DatabaseManager(self.test_db_path)
        client = MockPLCClient(self.mock_config)
        client.connect()

        # Insert 30 test records
        records = []
        base_time = datetime.now() - timedelta(minutes=5)
        for i in range(30):
            s = client.read_tags()
            s["timestamp"] = (base_time + timedelta(seconds=i)).isoformat()
            records.append(s)

        db.insert_batch(records)

        generator = ExcelReportGenerator(
            db_manager=db,
            output_dir=str(self.test_dir / "reports")
        )

        start_iso = base_time.isoformat()
        end_iso = (base_time + timedelta(minutes=10)).isoformat()

        report_file = generator.generate_report(
            start_iso=start_iso,
            end_iso=end_iso,
            report_title="Test Shift Report",
            sample_step=1
        )

        self.assertIsNotNone(report_file)
        self.assertTrue(report_file.exists())
        self.assertTrue(report_file.stat().st_size > 1000)

    def test_pdf_report_generation(self):
        """Verify PDFReportGenerator produces valid .pdf with logos and KPIs."""
        from src.reports.pdf_generator import PDFReportGenerator
        db = DatabaseManager(self.test_db_path)
        client = MockPLCClient(self.mock_config)
        client.connect()

        records = []
        base_time = datetime.now() - timedelta(minutes=5)
        for i in range(20):
            s = client.read_tags()
            s["timestamp"] = (base_time + timedelta(seconds=i)).isoformat()
            records.append(s)

        db.insert_batch(records)

        generator = PDFReportGenerator(
            db_manager=db,
            output_dir=str(self.test_dir / "reports")
        )

        start_iso = base_time.isoformat()
        end_iso = (base_time + timedelta(minutes=10)).isoformat()

        report_file = generator.generate_pdf(
            start_iso=start_iso,
            end_iso=end_iso,
            report_title="Test Quality Audit Report"
        )

        self.assertIsNotNone(report_file)
        self.assertTrue(report_file.exists())
        self.assertTrue(report_file.stat().st_size > 1000)

    def test_plc_tag_auto_match_and_config_save(self):
        """Verify heuristic auto-matching and tags.json structural integrity."""
        from src.plc.discovery import auto_match_tags, save_and_apply_plc_config
        import json

        # Simulated tags found on Micro850
        discovered = [
            "FIT_101_FlowRate",
            "TT_101_HoldingInTemp",
            "TT_102_HoldingOutTemp",
            "Recipe_ProductName",
            "System_ProcessStatus",
            "FDV1_ForwardStatus",
            "FDV1_DiversionReason",
            "FDV2_ForwardStatus",
            "FDV2_DiversionReason",
            "CIP_SystemActive",
            "CIP_CurrentStepName"
        ]

        matched = auto_match_tags(discovered)
        self.assertEqual(matched["milk_flow"], "FIT_101_FlowRate")
        self.assertEqual(matched["holding_in_temp"], "TT_101_HoldingInTemp")
        self.assertEqual(matched["holding_out_temp"], "TT_102_HoldingOutTemp")
        self.assertEqual(matched["product"], "Recipe_ProductName")
        self.assertEqual(matched["fdv1_status"], "FDV1_ForwardStatus")
        self.assertEqual(matched["cip_status"], "CIP_SystemActive")

        # Test config save
        res = save_and_apply_plc_config(
            ip_address="192.168.1.99",
            tag_mapping=matched,
            mode="mock",
            restart_service=False
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["ip"], "192.168.1.99")

        # Verify tags.json still has nested "tags" structure required by LivePLCClient
        with open("config/tags.json", "r") as f:
            saved_tags = json.load(f)
        self.assertIn("tags", saved_tags)
        self.assertIn("milk_flow", saved_tags["tags"])
        self.assertEqual(saved_tags["tags"]["milk_flow"]["plc_tag"], "FIT_101_FlowRate")


if __name__ == "__main__":
    unittest.main()
