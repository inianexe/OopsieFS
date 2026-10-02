from __future__ import annotations

import errno
import os
import stat
import time
from pathlib import Path

LOCAL_FUSE2 = Path(__file__).resolve().parent / "vendor/fuse2/lib/x86_64-linux-gnu/libfuse.so.2"
SYSTEM_FUSE2 = Path("/usr/lib/x86_64-linux-gnu/libfuse.so.2")
if SYSTEM_FUSE2.exists():
    os.environ.setdefault("FUSE_LIBRARY_PATH", str(SYSTEM_FUSE2))
elif LOCAL_FUSE2.exists():
    os.environ.setdefault("FUSE_LIBRARY_PATH", str(LOCAL_FUSE2))
else:
    os.environ.setdefault("FUSE_LIBRARY_PATH", "/usr/lib/x86_64-linux-gnu/libfuse3.so.3")

import fuse
from fuse import FUSE, FuseOSError, Operations


def _xattr_not_supported(*_args):
    return -errno.ENOTSUP


fuse.FUSE.setxattr = _xattr_not_supported
fuse.FUSE.getxattr = _xattr_not_supported
fuse.FUSE.listxattr = _xattr_not_supported
fuse.FUSE.removexattr = _xattr_not_supported

from oopsiefs_core import OopsieStore
from oopsiefs_config import store_root, tracked_root


ROOT = tracked_root()
STORE = store_root()
MOUNT_DEFAULT = Path(__file__).resolve().parent / "OopsieFS_Mount"

PORTAL_NAMES = {
    "Latest Changed": "latest",
    "Deleted Files": "deleted",
    "Version History": "versions",
    "All Files": "all",
}


class OopsieFuse(Operations):
    def __init__(self, root: Path):
        self.store = OopsieStore(root, STORE)
        self.store.initialize(scan_now=False)

    def _split(self, path: str) -> list[str]:
        return [part for part in path.strip("/").split("/") if part]

    def _portal_id(self, portal_name: str) -> str:
        try:
            return PORTAL_NAMES[portal_name]
        except KeyError as exc:
            raise FuseOSError(errno.ENOENT) from exc

    def _records_for_portal(self, portal_name: str):
        self.store.refresh_existing()
        return self.store.portal_records(self._portal_id(portal_name))

    def _record_for_virtual_path(self, path: str):
        parts = self._split(path)
        if len(parts) < 2:
            raise FuseOSError(errno.ENOENT)
        portal_name = parts[0]
        virtual_name = "/".join(parts[1:])
        for record in self._records_for_portal(portal_name):
            if self._display_name(record) == virtual_name:
                return record
        raise FuseOSError(errno.ENOENT)

    def _display_name(self, record) -> str:
        prefix = "RECOVERABLE__" if record.deleted else ""
        safe_path = record.rel_path.replace("/", "__")
        return f"{prefix}{safe_path}"

    def _real_path(self, record: object) -> Path:
        if record.deleted:
            item = self.store.meta["files"][record.file_id]
            return self.store.trash_dir / item["trash_rel_path"]
        return self.store.files_dir / record.rel_path

    def getattr(self, path, fh=None):
        now = time.time()
        if path == "/":
            return {
                "st_mode": stat.S_IFDIR | 0o755,
                "st_nlink": 2,
                "st_size": 0,
                "st_ctime": now,
                "st_mtime": now,
                "st_atime": now,
            }

        parts = self._split(path)
        if len(parts) == 1 and parts[0] in PORTAL_NAMES:
            return {
                "st_mode": stat.S_IFDIR | 0o755,
                "st_nlink": 2,
                "st_size": 0,
                "st_ctime": now,
                "st_mtime": now,
                "st_atime": now,
            }

        record = self._record_for_virtual_path(path)
        real_path = self._real_path(record)
        try:
            st = real_path.stat()
        except FileNotFoundError as exc:
            raise FuseOSError(errno.ENOENT) from exc
        return {
            "st_mode": stat.S_IFREG | 0o444,
            "st_nlink": 1,
            "st_size": st.st_size,
            "st_ctime": st.st_ctime,
            "st_mtime": st.st_mtime,
            "st_atime": st.st_atime,
        }

    def readdir(self, path, fh):
        parts = self._split(path)
        if path == "/":
            return [".", "..", *PORTAL_NAMES.keys()]
        if len(parts) == 1 and parts[0] in PORTAL_NAMES:
            names = [self._display_name(record) for record in self._records_for_portal(parts[0])]
            return [".", "..", *names]
        raise FuseOSError(errno.ENOTDIR)

    def opendir(self, path):
        self.getattr(path)
        return 0

    def releasedir(self, path, fh):
        return 0

    def open(self, path, flags):
        access_mode = flags & os.O_ACCMODE
        if access_mode != os.O_RDONLY:
            raise FuseOSError(errno.EACCES)
        record = self._record_for_virtual_path(path)
        real_path = self._real_path(record)
        return os.open(real_path, os.O_RDONLY)

    def read(self, path, size, offset, fh):
        os.lseek(fh, offset, os.SEEK_SET)
        return os.read(fh, size)

    def release(self, path, fh):
        os.close(fh)
        return 0

    def access(self, path, mode):
        if mode & os.W_OK:
            raise FuseOSError(errno.EACCES)
        self.getattr(path)
        return 0


def main() -> None:
    mountpoint = Path(os.environ.get("OOPSIEFS_MOUNT", MOUNT_DEFAULT))
    mountpoint.mkdir(parents=True, exist_ok=True)
    print(f"Mounting OopsieFS portals at {mountpoint}")
    print("Keep this terminal open. Press Ctrl+C to unmount.")
    debug = os.environ.get("OOPSIEFS_DEBUG") == "1"
    FUSE(OopsieFuse(ROOT), str(mountpoint), foreground=True, nothreads=True, ro=True, debug=debug)


if __name__ == "__main__":
    main()
