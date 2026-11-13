"""CLI 时间参数的格式契约。"""
import tempfile
import unittest
from datetime import datetime, timezone

import sau_cli
from sau_commands import arguments
from utils.time_utils import parse_aware_iso


class ScheduleArgumentTests(unittest.TestCase):
    def test_parses_utc_iso_with_z(self):
        self.assertEqual(
            arguments.parse_schedule("2026-11-12T10:30:00Z"),
            datetime(2026, 11, 12, 10, 30, tzinfo=timezone.utc),
        )

    def test_rejects_naive_schedule(self):
        for raw in ("2026-11-12 10:30", "2026-11-12T10:30:00"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                arguments.parse_schedule(raw)

    def test_rejects_non_utc_offset(self):
        with self.assertRaises(ValueError):
            arguments.parse_schedule("2026-11-12T18:30:00+08:00")

    def test_rejects_fractional_seconds(self):
        for raw in (
            "2026-11-12T10:30:00.500Z",
            "2026-11-12T10:30:00.000Z",
            "2026-11-12T10:30:00.0Z",
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                arguments.parse_schedule(raw)

    def test_parse_aware_iso_normalizes_short_fractions(self):
        self.assertEqual(
            parse_aware_iso("2026-11-12T10:30:00.5+00:00").microsecond,
            500000,
        )
        self.assertEqual(
            parse_aware_iso("2026-11-12T10:30:00.0000+00:00").microsecond,
            0,
        )

    def test_rejects_non_extended_iso_forms(self):
        for raw in (
            "20261201T003000Z",
            "2026-W49-2T00:30:00Z",
            "2026-11-12t10:30:00Z",
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                arguments.parse_schedule(raw)

    def test_accepts_zero_offset_forms(self):
        expected = datetime(2026, 11, 12, 10, 30, tzinfo=timezone.utc)
        for raw in (
            "2026-11-12T10:30:00+00:00",
            "2026-11-12T10:30:00+0000",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(arguments.parse_schedule(raw), expected)

    def test_rejects_non_zero_seconds(self):
        with self.assertRaises(ValueError):
            arguments.parse_schedule("2026-11-12T10:30:45Z")

    def test_omitted_schedule_means_immediate(self):
        self.assertEqual(arguments.parse_schedule(None), 0)

    def test_empty_schedule_is_rejected(self):
        with self.assertRaises(ValueError):
            arguments.parse_schedule("")

    def test_upload_parser_reads_utc_schedule(self):
        parser = sau_cli.build_parser()
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            args = parser.parse_args(
                [
                    "douyin",
                    "upload-video",
                    "--file",
                    video.name,
                    "--title",
                    "hello",
                    "--schedule",
                    "2026-11-12T10:30:00Z",
                ]
            )
        self.assertEqual(
            args.schedule,
            datetime(2026, 11, 12, 10, 30, tzinfo=timezone.utc),
        )

if __name__ == "__main__":
    unittest.main()
