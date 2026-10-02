from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from oopsiefs_config import scan_window_seconds


@dataclass
class FileRecord:
    file_id: str
    name: str
    rel_path: str
    original_rel_path: str
    size: int
    modified_at: float
    created_at: float
    deleted: bool
    versions: list[dict]


@dataclass
class CommandRecord:
    command_id: str
    action: str
    target: str
    created_at: float
    reversible: bool
    undone: bool
    details: str
    undo_data: dict


class OopsieStore:
    """Versioned file store with command history for the OopsieFS demo."""

    EXCLUDED_ROOTS = {
        "/dev",
        "/proc",
        "/run",
        "/sys",
        "/tmp",
        "/var/tmp",
    }
    EXCLUDED_NAMES = {
        ".cache",
        ".git",
        ".local/share/oopsiefs",
        ".venv",
        "__pycache__",
        "node_modules",
        "vendor",
    }
    MAX_SNAPSHOT_BYTES = 20 * 1024 * 1024

    def __init__(self, root: Path, store_dir: Path | None = None):
        self.root = root.resolve()
        self.files_dir = self.root
        if store_dir is None:
            store_dir = root / ".oopsie_store"
        self.store_dir = store_dir.resolve()
        self.version_dir = self.store_dir / "versions"
        self.trash_dir = self.store_dir / "trash"
        self.meta_path = self.store_dir / "metadata.json"
        self.meta: dict = {"files": {}, "commands": [], "events": []}
        self.scan_window_seconds = scan_window_seconds()

    def initialize(self, scan_now: bool = True) -> None:
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.version_dir.mkdir(parents=True, exist_ok=True)
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        if self.meta_path.exists():
            self._load()
        else:
            if scan_now and self.root != Path("/") and not any(self._iter_visible_files()):
                self.seed_samples()
            self.save()
        if scan_now:
            self.scan()

    def seed_samples(self) -> None:
        samples = {
            "OS_Project/oopsiefs_notes.md": "# OopsieFS\n\nUndoable file history for Linux.\n",
            "OS_Project/history_rules.py": "def view_for(path):\n    return 'latest_changed'\n",
            "Downloads/final-draft.txt": "This is a sample document for recovery tests.\n",
            "Logs/mount_error.log": "fusermount3: mount failed: permission denied\n",
        }
        for rel_path, content in samples.items():
            path = self.files_dir / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def save(self) -> None:
        self.meta_path.write_text(json.dumps(self.meta, indent=2), encoding="utf-8")

    def scan(self) -> None:
        if self.meta_path.exists():
            self._load()
        cutoff = time.time() - self.scan_window_seconds
        known_paths = {
            item["rel_path"]: file_id
            for file_id, item in self.meta["files"].items()
            if not item.get("deleted")
        }
        changed = False
        for path in self._iter_visible_files():
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime < cutoff:
                continue
            rel_path = path.relative_to(self.files_dir).as_posix()
            if rel_path in known_paths:
                self._refresh_record(known_paths[rel_path], path)
                continue
            file_id = uuid.uuid4().hex
            self.meta["files"][file_id] = {
                "name": path.name,
                "rel_path": rel_path,
                "original_rel_path": rel_path,
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
                "created_at": time.time(),
                "deleted": False,
                "trash_rel_path": None,
                "versions": [],
            }
            changed = True
        for item in list(self.meta["files"].values()):
            if item.get("deleted"):
                continue
            if item["modified_at"] < cutoff:
                continue
            if not (self.files_dir / item["rel_path"]).exists():
                item["deleted"] = True
                item["trash_rel_path"] = None
                item["modified_at"] = time.time()
                self._event("external_delete", item["name"], "File disappeared outside OopsieFS")
                changed = True
        if changed:
            self.save()

    def refresh_existing(self) -> None:
        if self.meta_path.exists():
            self._load()

    def index_path(self, path: Path, details: str = "External file change") -> None:
        if self.meta_path.exists():
            self._load()
        path = path.resolve()
        if self._is_excluded_path(path) or not path.is_file():
            return
        try:
            rel_path = path.relative_to(self.files_dir).as_posix()
            stat = path.stat()
        except (OSError, ValueError):
            return
        file_id = self._file_id_for_rel_path(rel_path)
        if file_id:
            self._refresh_record(file_id, path)
        else:
            file_id = uuid.uuid4().hex
            self.meta["files"][file_id] = {
                "name": path.name,
                "rel_path": rel_path,
                "original_rel_path": rel_path,
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
                "created_at": time.time(),
                "deleted": False,
                "trash_rel_path": None,
                "versions": [],
            }
        self._add_command("external_change", rel_path, details, {"file_id": file_id}, reversible=False)
        self.save()

    def mark_deleted_path(self, path: Path, details: str = "External file delete") -> None:
        if self.meta_path.exists():
            self._load()
        try:
            rel_path = path.resolve().relative_to(self.files_dir).as_posix()
        except ValueError:
            return
        file_id = self._file_id_for_rel_path(rel_path)
        if not file_id:
            return
        item = self.meta["files"][file_id]
        item["deleted"] = True
        item["trash_rel_path"] = None
        item["modified_at"] = time.time()
        self._add_command("external_delete", rel_path, details, {"file_id": file_id}, reversible=False)
        self.save()

    def index_recent_under(self, roots: list[Path]) -> None:
        cutoff = time.time() - self.scan_window_seconds
        for root in roots:
            if not root.exists() or not root.is_dir() or self._is_excluded_path(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda _error: None):
                current = Path(dirpath)
                if self._is_excluded_path(current):
                    dirnames[:] = []
                    continue
                dirnames[:] = [name for name in dirnames if not self._is_excluded_path(current / name)]
                for filename in filenames:
                    path = current / filename
                    try:
                        if path.stat().st_mtime >= cutoff:
                            self.index_path(path, "Manual recent index")
                    except OSError:
                        continue

    def records(self) -> list[FileRecord]:
        return [self._record(file_id, item) for file_id, item in self.meta["files"].items()]

    def command_history(self) -> list[CommandRecord]:
        return [self._command_record(item) for item in self.meta.get("commands", [])]

    def portal_records(self, portal: str) -> list[FileRecord]:
        records = self.records()
        if portal == "latest":
            return sorted([item for item in records if not item.deleted], key=lambda item: item.modified_at, reverse=True)
        if portal == "deleted":
            return sorted([item for item in records if item.deleted], key=lambda item: item.modified_at, reverse=True)
        if portal == "versions":
            return sorted([item for item in records if item.versions], key=lambda item: item.modified_at, reverse=True)
        if portal == "all":
            return sorted([item for item in records if not item.deleted], key=lambda item: item.rel_path.lower())
        return []

    def snapshot(self, file_id: str, note: str, record_command: bool = False) -> int | None:
        item = self.meta["files"][file_id]
        if item.get("deleted"):
            return None
        src = self.files_dir / item["rel_path"]
        if not src.exists():
            return None
        if src.stat().st_size > self.MAX_SNAPSHOT_BYTES:
            self._event("snapshot_skipped", item["name"], "File is larger than snapshot limit")
            return None
        version_id = uuid.uuid4().hex
        dst = self.version_dir / f"{file_id}_{version_id}{src.suffix}"
        shutil.copy2(src, dst)
        item["versions"].append(
            {
                "version_id": version_id,
                "stored_name": dst.name,
                "note": note,
                "created_at": time.time(),
                "size": dst.stat().st_size,
            }
        )
        self._refresh_record(file_id, src)
        version_index = len(item["versions"]) - 1
        self._event("snapshot", item["name"], note)
        if record_command:
            self._add_command(
                "snapshot",
                item["rel_path"],
                note,
                {"file_id": file_id, "version_index": version_index},
                reversible=False,
            )
        self.save()
        return version_index

    def edit_demo_file(self, file_id: str) -> None:
        item = self.meta["files"][file_id]
        if item.get("deleted"):
            return
        previous_index = self.snapshot(file_id, "Before edit", record_command=False)
        path = self.files_dir / item["rel_path"]
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8", errors="ignore") as handle:
            handle.write(f"\nOopsieFS tracked edit at {stamp}\n")
        self.snapshot(file_id, "After edit", record_command=False)
        self._add_command(
            "edit",
            item["rel_path"],
            "Appended a tracked demo edit",
            {"file_id": file_id, "version_index": previous_index},
        )
        self.save()

    def soft_delete(self, file_id: str, record_command: bool = True) -> None:
        item = self.meta["files"][file_id]
        if item.get("deleted"):
            return
        self.snapshot(file_id, "Before soft delete", record_command=False)
        src = self.files_dir / item["rel_path"]
        if not src.exists():
            return
        trash_name = f"{file_id}_{src.name}"
        dst = self.trash_dir / trash_name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        previous_path = item["rel_path"]
        item["deleted"] = True
        item["trash_rel_path"] = trash_name
        item["modified_at"] = time.time()
        self._event("delete", item["name"], "Moved into recovery storage")
        if record_command:
            self._add_command("delete", previous_path, "Soft-deleted file", {"file_id": file_id})
        self.save()

    def restore_deleted(self, file_id: str, record_command: bool = True) -> None:
        item = self.meta["files"][file_id]
        if not item.get("deleted"):
            return
        dst = self.files_dir / item["original_rel_path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst = dst.with_name(f"restored_{int(time.time())}_{dst.name}")
            item["rel_path"] = dst.relative_to(self.files_dir).as_posix()
        else:
            item["rel_path"] = item["original_rel_path"]
        if item.get("trash_rel_path"):
            src = self.trash_dir / item["trash_rel_path"]
            shutil.move(str(src), str(dst))
        elif item["versions"]:
            version = item["versions"][-1]
            shutil.copy2(self.version_dir / version["stored_name"], dst)
        else:
            raise ValueError("No trash copy or snapshot is available for this file")
        item["deleted"] = False
        item["trash_rel_path"] = None
        self._refresh_record(file_id, dst)
        self._event("restore", item["name"], "Restored from deleted files")
        if record_command:
            self._add_command("restore", item["rel_path"], "Restored deleted file", {"file_id": file_id})
        self.save()

    def restore_version(self, file_id: str, version_index: int, record_command: bool = True) -> None:
        item = self.meta["files"][file_id]
        if item.get("deleted") or not item["versions"]:
            return
        previous_index = self.snapshot(file_id, "Before version restore", record_command=False)
        self._restore_version_index(file_id, version_index)
        if record_command:
            self._add_command(
                "restore_version",
                item["rel_path"],
                f"Restored version {version_index + 1}",
                {"file_id": file_id, "version_index": previous_index},
            )
        self.save()

    def receive_file(self, filename: str, data: bytes, source: str = "LAN transfer") -> str:
        safe_name = Path(filename).name or f"received_{int(time.time())}.bin"
        received_dir = self._default_write_dir() / "Received"
        received_dir.mkdir(parents=True, exist_ok=True)
        dst = received_dir / safe_name
        if dst.exists():
            dst = received_dir / f"{int(time.time())}_{safe_name}"
        dst.write_bytes(data)
        self.index_path(dst, f"Received from {source}")
        rel_path = dst.relative_to(self.files_dir).as_posix()
        file_id = self._file_id_for_rel_path(rel_path)
        if file_id:
            self._add_command("receive", rel_path, f"Received from {source}", {"file_id": file_id})
            self.save()
        return rel_path

    def record_send(self, file_id: str, target: str) -> None:
        item = self.meta["files"][file_id]
        self._add_command("send", item["rel_path"], f"Sent to {target}", {"file_id": file_id}, reversible=False)
        self.save()

    def undo_command(self, command_id: str) -> str:
        command = next((item for item in self.meta["commands"] if item["command_id"] == command_id), None)
        if command is None:
            raise ValueError("Command not found")
        if command.get("undone"):
            raise ValueError("Command already undone")
        if not command.get("reversible"):
            raise ValueError("Command is not reversible")
        undo_data = command.get("undo_data", {})
        action = command["action"]
        file_id = undo_data.get("file_id")
        if not file_id:
            raise ValueError("Command has no file target")
        if action in {"edit", "restore_version"}:
            version_index = undo_data.get("version_index")
            if version_index is None:
                raise ValueError("No previous version available")
            self._restore_version_index(file_id, version_index)
        elif action == "delete":
            self.restore_deleted(file_id, record_command=False)
        elif action in {"restore", "receive"}:
            self.soft_delete(file_id, record_command=False)
        else:
            raise ValueError(f"Undo is not implemented for {action}")
        command["undone"] = True
        self._event("undo", command["target"], f"Undid {action}")
        self.save()
        return f"Undid {action}: {command['target']}"

    def original_path(self, file_id: str) -> Path:
        item = self.meta["files"][file_id]
        if item.get("deleted"):
            if item.get("trash_rel_path"):
                return self.trash_dir / item["trash_rel_path"]
            return self.files_dir / item["original_rel_path"]
        return self.files_dir / item["rel_path"]

    def _iter_visible_files(self):
        for dirpath, dirnames, filenames in os.walk(self.files_dir, topdown=True, onerror=lambda _error: None):
            current = Path(dirpath)
            if self._is_excluded_path(current):
                dirnames[:] = []
                continue
            dirnames[:] = [
                name
                for name in dirnames
                if not self._is_excluded_path(current / name)
            ]
            for filename in filenames:
                path = current / filename
                if not self._is_excluded_path(path) and path.is_file():
                    yield path

    def _is_excluded_path(self, path: Path) -> bool:
        resolved = path.absolute()
        if resolved == self.store_dir or self.store_dir in resolved.parents:
            return True
        resolved_text = resolved.as_posix()
        if resolved_text in self.EXCLUDED_ROOTS:
            return True
        if any(resolved_text.startswith(root + "/") for root in self.EXCLUDED_ROOTS):
            return True
        parts = resolved.parts
        return any(name in parts for name in self.EXCLUDED_NAMES)

    def _default_write_dir(self) -> Path:
        if self.files_dir == Path("/"):
            target = Path.home() / "OopsieFS_Received"
        else:
            target = self.files_dir
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _restore_version_index(self, file_id: str, version_index: int) -> None:
        item = self.meta["files"][file_id]
        if version_index < 0 or version_index >= len(item["versions"]):
            raise IndexError("Version index out of range")
        version = item["versions"][version_index]
        src = self.version_dir / version["stored_name"]
        dst = self.files_dir / item["rel_path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        self._refresh_record(file_id, dst)
        self._event("rewind", item["name"], version["note"])

    def _load(self) -> None:
        self.meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        self.meta.setdefault("files", {})
        self.meta.setdefault("commands", [])
        self.meta.setdefault("events", [])

    def _record(self, file_id: str, item: dict) -> FileRecord:
        return FileRecord(
            file_id=file_id,
            name=item["name"],
            rel_path=item["rel_path"],
            original_rel_path=item["original_rel_path"],
            size=item["size"],
            modified_at=item["modified_at"],
            created_at=item["created_at"],
            deleted=item["deleted"],
            versions=item["versions"],
        )

    def _command_record(self, item: dict) -> CommandRecord:
        return CommandRecord(
            command_id=item["command_id"],
            action=item["action"],
            target=item["target"],
            created_at=item["created_at"],
            reversible=item["reversible"],
            undone=item["undone"],
            details=item["details"],
            undo_data=item.get("undo_data", {}),
        )

    def _refresh_record(self, file_id: str, path: Path) -> None:
        stat = path.stat()
        item = self.meta["files"][file_id]
        rel_path = path.relative_to(self.files_dir).as_posix()
        item["name"] = path.name
        item["rel_path"] = rel_path
        item.setdefault("original_rel_path", rel_path)
        item["size"] = stat.st_size
        item["modified_at"] = stat.st_mtime

    def _file_id_for_rel_path(self, rel_path: str) -> str | None:
        for file_id, item in self.meta["files"].items():
            if item["rel_path"] == rel_path and not item.get("deleted"):
                return file_id
        return None

    def _add_command(
        self,
        action: str,
        target: str,
        details: str,
        undo_data: dict,
        reversible: bool = True,
    ) -> None:
        self.meta.setdefault("commands", []).insert(
            0,
            {
                "command_id": uuid.uuid4().hex,
                "action": action,
                "target": target,
                "details": details,
                "created_at": time.time(),
                "reversible": reversible,
                "undone": False,
                "undo_data": undo_data,
            },
        )
        self.meta["commands"] = self.meta["commands"][:100]
        self._event(action, target, details)

    def _event(self, kind: str, name: str, detail: str) -> None:
        self.meta.setdefault("events", []).insert(
            0,
            {
                "kind": kind,
                "name": name,
                "detail": detail,
                "created_at": time.time(),
            },
        )
        self.meta["events"] = self.meta["events"][:50]
