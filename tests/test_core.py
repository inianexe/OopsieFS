from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from oopsiefs_core import OopsieStore


class OopsieStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["OOPSIEFS_SCAN_WINDOW_SECONDS"] = "3600"
        base = Path.cwd() / ".testdata"
        base.mkdir(exist_ok=True)
        self.tempdir = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.tempdir.name) / "workspace"
        self.store_dir = Path(self.tempdir.name) / "store"
        self.root.mkdir()
        self.store = OopsieStore(self.root, self.store_dir)
        self.store.initialize(scan_now=False)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def create_indexed_file(self, rel_path: str = "notes/demo.txt", content: str = "hello") -> str:
        path = self.root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.store.index_path(path, "test index")
        return next(item.file_id for item in self.store.records() if item.rel_path == rel_path)

    def test_index_edit_snapshot_and_undo(self) -> None:
        file_id = self.create_indexed_file()

        self.store.edit_demo_file(file_id)
        record = next(item for item in self.store.records() if item.file_id == file_id)
        self.assertEqual(len(record.versions), 2)
        self.assertIn(record, self.store.portal_records("versions"))

        command = next(item for item in self.store.command_history() if item.action == "edit")
        self.store.undo_command(command.command_id)

        text = (self.root / "notes/demo.txt").read_text(encoding="utf-8")
        self.assertEqual(text, "hello")

    def test_soft_delete_restore_and_undo_restore(self) -> None:
        file_id = self.create_indexed_file("docs/report.txt", "draft")

        self.store.soft_delete(file_id)
        self.assertFalse((self.root / "docs/report.txt").exists())
        self.assertEqual(len(self.store.portal_records("deleted")), 1)

        self.store.restore_deleted(file_id)
        self.assertTrue((self.root / "docs/report.txt").exists())

        command = next(item for item in self.store.command_history() if item.action == "restore")
        self.store.undo_command(command.command_id)
        record = next(item for item in self.store.records() if item.file_id == file_id)
        self.assertTrue(record.deleted)

    def test_invalid_version_index_is_rejected(self) -> None:
        file_id = self.create_indexed_file()
        self.store.snapshot(file_id, "baseline")

        with self.assertRaises(IndexError):
            self.store.restore_version(file_id, 99)


if __name__ == "__main__":
    unittest.main()
