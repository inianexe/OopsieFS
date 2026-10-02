from __future__ import annotations

import os
import socket
import tempfile
import time
import unittest
from pathlib import Path

from oopsiefs_core import OopsieStore
from oopsiefs_transfer import TransferReceiver, send_file_by_code


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TransferTests(unittest.TestCase):
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

    def test_send_file_by_receiver_code(self) -> None:
        source = self.root / "send-me.txt"
        source.write_text("payload", encoding="utf-8")
        self.store.index_path(source, "test index")

        discovery_port = free_udp_port()
        receiver = TransferReceiver(self.store, http_port=0, discovery_port=discovery_port, ttl_seconds=30)
        receiver.start()
        try:
            time.sleep(0.1)
            result = send_file_by_code(source, receiver.code, discovery_port=discovery_port, timeout=3)
            self.assertIn("send-me.txt", result)
        finally:
            receiver.stop()

        received = self.root / "Received" / "send-me.txt"
        self.assertTrue(received.exists())
        self.assertEqual(received.read_text(encoding="utf-8"), "payload")


if __name__ == "__main__":
    unittest.main()
