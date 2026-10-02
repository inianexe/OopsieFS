from __future__ import annotations

import ctypes
import errno
import os
import select
import struct
import threading
from pathlib import Path
from typing import Callable


IN_ACCESS = 0x00000001
IN_MODIFY = 0x00000002
IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800
IN_ISDIR = 0x40000000
IN_IGNORED = 0x00008000

WATCH_MASK = IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE | IN_DELETE | IN_MOVED_FROM | IN_ATTRIB


class InotifyWatcher:
    def __init__(
        self,
        roots: list[Path],
        on_change: Callable[[Path], None],
        on_delete: Callable[[Path], None],
        should_skip: Callable[[Path], bool],
        on_log: Callable[[str], None] | None = None,
    ):
        self.roots = roots
        self.on_change = on_change
        self.on_delete = on_delete
        self.should_skip = should_skip
        self.on_log = on_log or (lambda _message: None)
        self._libc = ctypes.CDLL("libc.so.6", use_errno=True)
        self._fd: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._wd_to_path: dict[int, Path] = {}

    def start(self) -> None:
        if self._thread:
            return
        self._fd = self._libc.inotify_init1(os.O_NONBLOCK)
        if self._fd < 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
        for root in self.roots:
            if root.exists() and root.is_dir() and not self.should_skip(root):
                self._add_tree(root)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.on_log(f"Watching {len(self._wd_to_path)} directories")

    def stop(self) -> None:
        self._stop.set()
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def _add_watch(self, path: Path) -> None:
        if self._fd is None:
            return
        wd = self._libc.inotify_add_watch(self._fd, os.fsencode(path), WATCH_MASK)
        if wd < 0:
            code = ctypes.get_errno()
            if code not in {errno.EACCES, errno.ENOENT, errno.ENOTDIR}:
                self.on_log(f"Could not watch {path}: {os.strerror(code)}")
            return
        self._wd_to_path[wd] = path

    def _add_tree(self, root: Path) -> None:
        for dirpath, dirnames, _filenames in os.walk(root, topdown=True, onerror=lambda _error: None):
            current = Path(dirpath)
            if self.should_skip(current):
                dirnames[:] = []
                continue
            dirnames[:] = [name for name in dirnames if not self.should_skip(current / name)]
            self._add_watch(current)

    def _run(self) -> None:
        while not self._stop.is_set() and self._fd is not None:
            try:
                readable, _writable, _errors = select.select([self._fd], [], [], 0.5)
            except OSError:
                break
            if not readable:
                continue
            try:
                data = os.read(self._fd, 65536)
            except BlockingIOError:
                continue
            except OSError:
                break
            offset = 0
            while offset + 16 <= len(data):
                wd, mask, _cookie, name_len = struct.unpack_from("iIII", data, offset)
                offset += 16
                raw_name = data[offset : offset + name_len].rstrip(b"\0")
                offset += name_len
                parent = self._wd_to_path.get(wd)
                if parent is None:
                    continue
                path = parent / os.fsdecode(raw_name) if raw_name else parent
                if mask & IN_IGNORED:
                    self._wd_to_path.pop(wd, None)
                    continue
                if mask & IN_ISDIR and mask & (IN_CREATE | IN_MOVED_TO):
                    if path.exists() and path.is_dir() and not self.should_skip(path):
                        self._add_tree(path)
                    continue
                if mask & (IN_DELETE | IN_MOVED_FROM):
                    self.on_delete(path)
                elif mask & (IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE | IN_ATTRIB | IN_MODIFY):
                    self.on_change(path)
