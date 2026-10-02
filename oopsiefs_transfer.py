from __future__ import annotations

import json
import random
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import quote, unquote

from oopsiefs_core import OopsieStore


DISCOVERY_PORT = 8766
HTTP_PORT = 8765


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def _local_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        value = sock.getsockname()[0]
        sock.close()
        return value
    except OSError:
        return "127.0.0.1"


class TransferReceiver:
    def __init__(
        self,
        store: OopsieStore,
        http_port: int = HTTP_PORT,
        discovery_port: int = DISCOVERY_PORT,
        ttl_seconds: int = 300,
        on_log: Callable[[str], None] | None = None,
    ):
        self.store = store
        self.http_port = http_port
        self.discovery_port = discovery_port
        self.ttl_seconds = ttl_seconds
        self.on_log = on_log or (lambda _message: None)
        self.code = f"{random.randint(100000, 999999)}"
        self.expires_at = time.time() + ttl_seconds
        self._httpd: ThreadingHTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._udp_thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path != "/upload":
                    self.send_error(404)
                    return
                if time.time() > receiver.expires_at:
                    self.send_error(403, "Transfer code expired")
                    return
                if self.headers.get("X-Oopsie-Code") != receiver.code:
                    self.send_error(403, "Invalid transfer code")
                    return
                length = int(self.headers.get("Content-Length", "0"))
                filename = unquote(self.headers.get("X-Filename", "received.bin"))
                data = self.rfile.read(length)
                rel_path = receiver.store.receive_file(filename, data, self.client_address[0])
                receiver.on_log(f"Received {filename} as {rel_path}")
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "path": rel_path}).encode("utf-8"))

            def log_message(self, _format, *_args):
                return

        self._httpd = ReusableThreadingHTTPServer(("0.0.0.0", self.http_port), Handler)
        self.http_port = self._httpd.server_address[1]
        self._http_thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._http_thread.start()
        self._udp_thread = threading.Thread(target=self._serve_discovery, daemon=True)
        self._udp_thread.start()
        self.on_log(f"Receiver started at {_local_ip()}:{self.http_port} with code {self.code}")

    def stop(self) -> None:
        self._stop.set()
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._http_thread and self._http_thread.is_alive():
            self._http_thread.join(timeout=2)
        if self._udp_thread and self._udp_thread.is_alive():
            self._udp_thread.join(timeout=2)
        self.on_log("Receiver stopped")

    def _serve_discovery(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self.discovery_port))
            sock.settimeout(0.4)
            while not self._stop.is_set():
                try:
                    payload, addr = sock.recvfrom(2048)
                except socket.timeout:
                    continue
                try:
                    message = json.loads(payload.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                if message.get("type") != "oopsiefs_lookup" or message.get("code") != self.code:
                    continue
                if time.time() > self.expires_at:
                    continue
                response = {
                    "type": "oopsiefs_peer",
                    "code": self.code,
                    "host": _local_ip(),
                    "port": self.http_port,
                }
                sock.sendto(json.dumps(response).encode("utf-8"), addr)
        finally:
            sock.close()


def resolve_code(code: str, discovery_port: int = DISCOVERY_PORT, timeout: float = 4.0) -> tuple[str, int]:
    payload = json.dumps({"type": "oopsiefs_lookup", "code": code}).encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.6)
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            sock.sendto(payload, ("255.255.255.255", discovery_port))
            sock.sendto(payload, ("127.0.0.1", discovery_port))
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            message = json.loads(data.decode("utf-8"))
            if message.get("type") == "oopsiefs_peer" and message.get("code") == code:
                return message.get("host") or addr[0], int(message["port"])
    finally:
        sock.close()
    raise TimeoutError("No receiver found for that code")


def send_file_by_code(
    path: Path,
    code: str,
    discovery_port: int = DISCOVERY_PORT,
    timeout: float = 4.0,
) -> str:
    host, port = resolve_code(code, discovery_port=discovery_port, timeout=timeout)
    data = path.read_bytes()
    request = urllib.request.Request(
        f"http://{host}:{port}/upload",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(data)),
            "X-Filename": quote(path.name),
            "X-Oopsie-Code": code,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise ConnectionError(f"Transfer failed: {exc}") from exc
