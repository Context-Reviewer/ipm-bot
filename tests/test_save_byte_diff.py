from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from ipm_bot.save.byte_diff import diff_binary_files, diff_binary_payloads, render_binary_diff


class SaveByteDiffTests(unittest.TestCase):
    def test_diff_binary_payloads_returns_no_changes_for_identical_payloads(self) -> None:
        self.assertEqual(diff_binary_payloads(b"abc", b"abc"), [])

    def test_diff_binary_payloads_groups_contiguous_changed_span(self) -> None:
        changes = diff_binary_payloads(b"abc123xyz", b"abc456xyz")

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].start_offset, 3)
        self.assertEqual(changes[0].before_bytes, b"123")
        self.assertEqual(changes[0].after_bytes, b"456")

    def test_diff_binary_payloads_handles_inserted_tail(self) -> None:
        changes = diff_binary_payloads(b"abcdef", b"abcXYZdef")

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].start_offset, 3)
        self.assertEqual(changes[0].before_bytes, b"")
        self.assertEqual(changes[0].after_bytes, b"XYZ")

    def test_diff_binary_files_reads_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            before_path = root / "before.dat"
            after_path = root / "after.dat"
            before_path.write_bytes(b"abc123")
            after_path.write_bytes(b"abc124")

            changes = diff_binary_files(before_path, after_path)

            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0].start_offset, 5)
            self.assertEqual(changes[0].before_bytes, b"3")
            self.assertEqual(changes[0].after_bytes, b"4")

    def test_render_binary_diff_includes_offsets(self) -> None:
        changes = diff_binary_payloads(b"abc123", b"abc124")

        rendered = render_binary_diff(changes)

        self.assertIn("offset=0x00000005", rendered)
        self.assertIn("before_len=1", rendered)
        self.assertIn("after_len=1", rendered)
