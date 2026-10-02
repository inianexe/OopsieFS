from __future__ import annotations

import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from oopsiefs_core import CommandRecord, FileRecord, OopsieStore
from oopsiefs_config import scan_window_seconds, store_root, tracked_root, watched_roots
from oopsiefs_transfer import TransferReceiver, send_file_by_code
from oopsiefs_watcher import InotifyWatcher


ROOT = tracked_root()
STORE = store_root()


VIEWS = [
    ("latest", "Latest Changed"),
    ("commands", "Command History"),
    ("deleted", "Deleted Files"),
    ("versions", "Version History"),
    ("all", "All Files"),
    ("transfer", "File Transfer"),
]


class OopsieApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("OopsieFS")
        self.geometry("1180x740")
        self.minsize(980, 620)
        self.configure(bg="#f4f1ea")

        self.store = OopsieStore(ROOT, STORE)
        self.store.initialize(scan_now=False)
        self.active_view = "latest"
        self.selected_file_id: str | None = None
        self.selected_command_id: str | None = None
        self.file_rows: dict[str, str] = {}
        self.command_rows: dict[str, str] = {}
        self.receiver: TransferReceiver | None = None
        self.index_running = False
        self.watcher: InotifyWatcher | None = None

        self._setup_style()
        self._build_ui()
        self.refresh(scan=False)
        self.after(250, self.start_watcher)
        self.after(2000, self.periodic_refresh)

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview", rowheight=32, font=("DejaVu Sans", 10))
        style.configure("Treeview.Heading", font=("DejaVu Sans", 10, "bold"))
        style.configure("TButton", font=("DejaVu Sans", 10, "bold"), padding=8)

    def _build_ui(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self.sidebar = tk.Frame(self, bg="#fbf7ef", width=230, padx=16, pady=16)
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=(14, 8), pady=14)
        self.sidebar.grid_propagate(False)
        self.main = tk.Frame(self, bg="#fffaf2", padx=18, pady=16)
        self.main.grid(row=0, column=1, sticky="nsew", padx=8, pady=14)
        self.main.columnconfigure(0, weight=1)
        self.main.rowconfigure(4, weight=1)
        self.inspector = tk.Frame(self, bg="#fbf7ef", width=320, padx=16, pady=16)
        self.inspector.grid(row=0, column=2, sticky="nsew", padx=(8, 14), pady=14)
        self.inspector.grid_propagate(False)

        self._build_sidebar()
        self._build_main()
        self._build_inspector()

    def _build_sidebar(self) -> None:
        tk.Label(self.sidebar, text="OopsieFS", bg="#fbf7ef", fg="#202020", font=("DejaVu Sans", 24, "bold")).pack(anchor="w")
        tk.Label(
            self.sidebar,
            text="Undoable file history and local file transfer.",
            bg="#fbf7ef",
            fg="#66615a",
            wraplength=190,
            justify="left",
        ).pack(anchor="w", pady=(2, 18))

        self.view_buttons: dict[str, tk.Button] = {}
        for view_id, name in VIEWS:
            button = tk.Button(
                self.sidebar,
                text=name,
                anchor="w",
                relief="flat",
                bd=0,
                bg="#fbf7ef",
                fg="#202020",
                activebackground="#ece3d4",
                font=("DejaVu Sans", 10, "bold"),
                padx=12,
                pady=10,
                command=lambda value=view_id: self.set_view(value),
            )
            button.pack(fill="x", pady=3)
            self.view_buttons[view_id] = button

        tk.Frame(self.sidebar, height=1, bg="#ded4c4").pack(fill="x", pady=16)
        tk.Label(
            self.sidebar,
            text=f"Tracked root\n{ROOT}\n\nStore\n{STORE}",
            bg="#fbf7ef",
            fg="#66615a",
            wraplength=190,
            justify="left",
            font=("DejaVu Sans", 9),
        ).pack(anchor="w")
        ttk.Button(self.sidebar, text="Open tracked root", command=self.open_workspace).pack(fill="x", pady=(14, 4))
        ttk.Button(self.sidebar, text="Refresh view", command=lambda: self.refresh(scan=False)).pack(fill="x", pady=(0, 4))
        ttk.Button(self.sidebar, text="Index recent files", command=self.start_bounded_index).pack(fill="x")

    def _build_main(self) -> None:
        self.title_label = tk.Label(self.main, text="", bg="#fffaf2", fg="#202020", font=("DejaVu Sans", 24, "bold"))
        self.title_label.grid(row=0, column=0, sticky="w")
        self.summary_label = tk.Label(self.main, text="", bg="#fffaf2", fg="#66615a", justify="left")
        self.summary_label.grid(row=1, column=0, sticky="ew", pady=(4, 12))

        toolbar = tk.Frame(self.main, bg="#fffaf2")
        toolbar.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        toolbar.columnconfigure(0, weight=1)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.populate_current_view())
        tk.Entry(toolbar, textvariable=self.search_var, relief="flat", font=("DejaVu Sans", 11)).grid(
            row=0, column=0, sticky="ew", ipady=9, padx=(0, 8)
        )
        ttk.Button(toolbar, text="Tracked edit", command=self.demo_edit).grid(row=0, column=1, padx=4)
        ttk.Button(toolbar, text="Soft delete", command=self.soft_delete).grid(row=0, column=2, padx=4)
        ttk.Button(toolbar, text="Restore", command=self.restore_selected).grid(row=0, column=3, padx=4)
        ttk.Button(toolbar, text="Undo command", command=self.undo_selected_command).grid(row=0, column=4, padx=4)

        self.transfer_panel = tk.Frame(self.main, bg="#fff4df", padx=12, pady=12)
        self.transfer_panel.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        self.transfer_panel.columnconfigure(1, weight=1)
        ttk.Button(self.transfer_panel, text="Start receiving", command=self.start_receiver).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(self.transfer_panel, text="Stop receiving", command=self.stop_receiver).grid(row=0, column=1, sticky="w")
        self.code_label = tk.Label(self.transfer_panel, text="Receive code: inactive", bg="#fff4df", fg="#202020", font=("DejaVu Sans", 11, "bold"))
        self.code_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        tk.Label(self.transfer_panel, text="Receiver code", bg="#fff4df", fg="#66615a").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.target_code = tk.StringVar()
        tk.Entry(self.transfer_panel, textvariable=self.target_code, relief="flat", font=("DejaVu Sans", 11)).grid(
            row=2, column=1, sticky="ew", ipady=7, padx=(8, 8), pady=(10, 0)
        )
        ttk.Button(self.transfer_panel, text="Send selected file", command=self.send_selected_file).grid(row=2, column=2, pady=(10, 0))

        self.tree_frame = tk.Frame(self.main, bg="#fffaf2")
        self.tree_frame.grid(row=4, column=0, sticky="nsew")
        self.tree_frame.columnconfigure(0, weight=1)
        self.tree_frame.rowconfigure(0, weight=1)

    def _build_inspector(self) -> None:
        self.inspect_title = tk.Label(
            self.inspector,
            text="Select an item",
            bg="#fbf7ef",
            fg="#202020",
            font=("DejaVu Sans", 17, "bold"),
            wraplength=270,
            justify="left",
        )
        self.inspect_title.pack(anchor="w")
        self.inspect_path = tk.Label(self.inspector, text="", bg="#fbf7ef", fg="#66615a", wraplength=270, justify="left")
        self.inspect_path.pack(anchor="w", pady=(6, 16))
        self.info_text = tk.Text(self.inspector, height=12, relief="flat", bg="#fff4df", fg="#202020", padx=10, pady=10, wrap="word")
        self.info_text.pack(fill="x")
        self.info_text.configure(state="disabled")
        tk.Label(self.inspector, text="Versions", bg="#fbf7ef", fg="#202020", font=("DejaVu Sans", 13, "bold")).pack(anchor="w", pady=(18, 6))
        self.version_list = tk.Listbox(self.inspector, height=10, relief="flat", bg="#ffffff", fg="#202020", activestyle="none")
        self.version_list.pack(fill="both", expand=True)
        ttk.Button(self.inspector, text="Restore selected version", command=self.restore_version).pack(fill="x", pady=(10, 4))
        ttk.Button(self.inspector, text="Open file/folder", command=self.open_selected).pack(fill="x")

    def set_view(self, view_id: str) -> None:
        self.active_view = view_id
        self.refresh()

    def refresh(self, scan: bool = True) -> None:
        if scan:
            self.store.refresh_existing()
        for view_id, button in self.view_buttons.items():
            button.configure(bg="#ece3d4" if view_id == self.active_view else "#fbf7ef")
        view_name = dict(VIEWS)[self.active_view]
        self.title_label.configure(text=view_name)
        summaries = {
            "latest": f"Files changed in the last {scan_window_seconds() // 60} minutes.",
            "commands": "Operations performed through OopsieFS. Reversible commands can be undone.",
            "deleted": "Files held in recovery storage.",
            "versions": "Files with restorable snapshots.",
            "all": "All active files indexed by OopsieFS.",
            "transfer": "Send and receive files on the same Wi-Fi using a short code.",
        }
        self.summary_label.configure(text=summaries[self.active_view])
        self.transfer_panel.grid() if self.active_view == "transfer" else self.transfer_panel.grid_remove()
        self.populate_current_view()

    def start_watcher(self) -> None:
        if self.watcher:
            return
        roots = watched_roots()
        if not roots:
            self.summary_label.configure(text="No watched folders found. Use Index recent files or set OOPSIEFS_WATCH_ROOTS.")
            return
        try:
            self.watcher = InotifyWatcher(
                roots,
                on_change=self.store.index_path,
                on_delete=self.store.mark_deleted_path,
                should_skip=self.store._is_excluded_path,
                on_log=lambda message: self.after(0, lambda: self.summary_label.configure(text=message)),
            )
            self.watcher.start()
        except OSError as exc:
            self.summary_label.configure(text=f"Watcher failed: {exc}")

    def periodic_refresh(self) -> None:
        self.refresh(scan=False)
        self.after(2000, self.periodic_refresh)

    def start_bounded_index(self) -> None:
        if self.index_running:
            return
        self.index_running = True
        self.summary_label.configure(text="Indexing recent files in watched folders...")

        def worker() -> None:
            error = None
            try:
                self.store.index_recent_under(watched_roots())
            except Exception as exc:
                error = exc
            self.after(0, lambda: self.finish_bounded_index(error))

        threading.Thread(target=worker, daemon=True).start()

    def finish_bounded_index(self, error: Exception | None) -> None:
        self.index_running = False
        if error is not None:
            messagebox.showerror("OopsieFS", f"Index failed: {error}")
        self.refresh(scan=False)

    def populate_current_view(self) -> None:
        for child in self.tree_frame.winfo_children():
            child.destroy()
        self.selected_file_id = None
        self.selected_command_id = None
        self.file_rows.clear()
        self.command_rows.clear()
        if self.active_view == "commands":
            self.populate_commands()
        elif self.active_view == "transfer":
            self.populate_files("latest")
        else:
            self.populate_files(self.active_view)

    def populate_files(self, portal: str) -> None:
        columns = ("name", "path", "size", "versions", "modified")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", selectmode="browse")
        for col, label in zip(columns, ["File", "Path", "Size", "Versions", "Modified"]):
            self.tree.heading(col, text=label)
        self.tree.column("name", width=210)
        self.tree.column("path", width=360)
        self.tree.column("size", width=80, anchor="e")
        self.tree.column("versions", width=80, anchor="center")
        self.tree.column("modified", width=140)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.on_file_select())

        query = self.search_var.get().lower().strip()
        for record in self.store.portal_records(portal):
            if query and query not in record.name.lower() and query not in record.rel_path.lower():
                continue
            row_id = self.tree.insert(
                "",
                "end",
                values=(record.name, record.rel_path, self.format_size(record.size), len(record.versions), self.format_time(record.modified_at)),
            )
            self.file_rows[row_id] = record.file_id
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.on_file_select()
        else:
            self.show_empty_inspector("No files", "This view has no matching files.")

    def populate_commands(self) -> None:
        columns = ("time", "action", "target", "status")
        self.command_tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", selectmode="browse")
        for col, label in zip(columns, ["Time", "Action", "Target", "Status"]):
            self.command_tree.heading(col, text=label)
        self.command_tree.column("time", width=140)
        self.command_tree.column("action", width=120)
        self.command_tree.column("target", width=420)
        self.command_tree.column("status", width=120)
        self.command_tree.grid(row=0, column=0, sticky="nsew")
        self.command_tree.bind("<<TreeviewSelect>>", lambda _event: self.on_command_select())
        query = self.search_var.get().lower().strip()
        for command in self.store.command_history():
            if query and query not in command.target.lower() and query not in command.action.lower():
                continue
            status = "Undone" if command.undone else ("Undoable" if command.reversible else "Logged")
            row_id = self.command_tree.insert(
                "",
                "end",
                values=(self.format_time(command.created_at), command.action, command.target, status),
            )
            self.command_rows[row_id] = command.command_id
        children = self.command_tree.get_children()
        if children:
            self.command_tree.selection_set(children[0])
            self.on_command_select()
        else:
            self.show_empty_inspector("No commands", "Use tracked edit, delete, restore, or transfer to create history.")

    def on_file_select(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        self.selected_file_id = self.file_rows[selected[0]]
        record = self.selected_record()
        if record:
            self.show_file(record)

    def on_command_select(self) -> None:
        selected = self.command_tree.selection()
        if not selected:
            return
        self.selected_command_id = self.command_rows[selected[0]]
        command = self.selected_command()
        if command:
            self.show_command(command)

    def show_file(self, record: FileRecord) -> None:
        self.inspect_title.configure(text=record.name)
        self.inspect_path.configure(text=record.rel_path)
        self.set_info(
            f"Status: {'Deleted, recoverable' if record.deleted else 'Active'}\n"
            f"Original: {record.original_rel_path}\n"
            f"Size: {self.format_size(record.size)}\n"
            f"Modified: {self.format_time(record.modified_at)}\n"
            f"Versions: {len(record.versions)}"
        )
        self.version_list.delete(0, "end")
        for index, version in enumerate(record.versions):
            self.version_list.insert("end", f"{index + 1}. {version['note']} · {self.format_time(version['created_at'])}")

    def show_command(self, command: CommandRecord) -> None:
        self.inspect_title.configure(text=command.action)
        self.inspect_path.configure(text=command.target)
        self.set_info(
            f"Time: {self.format_time(command.created_at)}\n"
            f"Details: {command.details}\n"
            f"Reversible: {'yes' if command.reversible else 'no'}\n"
            f"Undone: {'yes' if command.undone else 'no'}"
        )
        self.version_list.delete(0, "end")

    def set_info(self, text: str) -> None:
        self.info_text.configure(state="normal")
        self.info_text.delete("1.0", "end")
        self.info_text.insert("end", text)
        self.info_text.configure(state="disabled")

    def show_empty_inspector(self, title: str, text: str) -> None:
        self.inspect_title.configure(text=title)
        self.inspect_path.configure(text="")
        self.set_info(text)
        self.version_list.delete(0, "end")

    def selected_record(self) -> FileRecord | None:
        if self.selected_file_id is None:
            return None
        return next((item for item in self.store.records() if item.file_id == self.selected_file_id), None)

    def selected_command(self) -> CommandRecord | None:
        if self.selected_command_id is None:
            return None
        return next((item for item in self.store.command_history() if item.command_id == self.selected_command_id), None)

    def demo_edit(self) -> None:
        if not self.require_file_selection():
            return
        record = self.selected_record()
        if record and record.deleted:
            messagebox.showinfo("OopsieFS", "Restore the file before editing it.")
            return
        try:
            self.store.edit_demo_file(self.selected_file_id)
        except OSError as exc:
            messagebox.showerror("OopsieFS", f"Could not edit file: {exc}")
            return
        self.refresh()

    def soft_delete(self) -> None:
        if not self.require_file_selection():
            return
        try:
            self.store.soft_delete(self.selected_file_id)
        except OSError as exc:
            messagebox.showerror("OopsieFS", f"Could not delete file: {exc}")
            return
        self.active_view = "deleted"
        self.refresh()

    def restore_selected(self) -> None:
        if not self.require_file_selection():
            return
        record = self.selected_record()
        if record and record.deleted:
            try:
                self.store.restore_deleted(self.selected_file_id)
            except (OSError, ValueError) as exc:
                messagebox.showerror("OopsieFS", f"Could not restore file: {exc}")
                return
            self.refresh()
        else:
            messagebox.showinfo("OopsieFS", "This file is active. Use Restore selected version for version recovery.")

    def restore_version(self) -> None:
        if not self.require_file_selection():
            return
        selected = self.version_list.curselection()
        if not selected:
            messagebox.showinfo("OopsieFS", "Pick a version first.")
            return
        try:
            self.store.restore_version(self.selected_file_id, selected[0])
        except OSError as exc:
            messagebox.showerror("OopsieFS", f"Could not restore version: {exc}")
            return
        self.refresh()

    def undo_selected_command(self) -> None:
        if self.selected_command_id is None:
            messagebox.showinfo("OopsieFS", "Select a command from Command History first.")
            return
        try:
            message = self.store.undo_command(self.selected_command_id)
        except ValueError as exc:
            messagebox.showinfo("OopsieFS", str(exc))
            return
        messagebox.showinfo("OopsieFS", message)
        self.refresh()

    def start_receiver(self) -> None:
        if self.receiver:
            messagebox.showinfo("OopsieFS", "Receiver is already running.")
            return
        self.receiver = TransferReceiver(self.store, on_log=self.log_transfer)
        self.receiver.start()
        self.code_label.configure(text=f"Receive code: {self.receiver.code}  Expires in 5 minutes")

    def stop_receiver(self) -> None:
        if self.receiver:
            self.receiver.stop()
            self.receiver = None
        self.code_label.configure(text="Receive code: inactive")

    def send_selected_file(self) -> None:
        if not self.require_file_selection():
            return
        code = self.target_code.get().strip()
        if not code:
            messagebox.showinfo("OopsieFS", "Enter the receiver code first.")
            return
        path = self.store.original_path(self.selected_file_id)
        try:
            result = send_file_by_code(path, code)
        except Exception as exc:
            messagebox.showerror("OopsieFS", str(exc))
            return
        self.store.record_send(self.selected_file_id, code)
        self.log_transfer(f"Sent {path.name} using code {code}: {result}")
        self.refresh()

    def log_transfer(self, message: str) -> None:
        self.store._event("transfer", "File Transfer", message)
        self.store.save()
        if self.active_view == "transfer":
            self.set_info(message)

    def open_selected(self) -> None:
        if not self.require_file_selection():
            return
        path = self.store.original_path(self.selected_file_id)
        if not path.exists():
            path = path.parent
        self.open_path(path)

    def open_workspace(self) -> None:
        self.open_path(ROOT)

    def open_path(self, path: Path) -> None:
        if sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["explorer", str(path)])

    def require_file_selection(self) -> bool:
        if self.selected_file_id is None:
            messagebox.showinfo("OopsieFS", "Select a file first.")
            return False
        return True

    @staticmethod
    def format_size(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    @staticmethod
    def format_time(value: float) -> str:
        return datetime.fromtimestamp(value).strftime("%b %d, %H:%M")


def main() -> None:
    app = OopsieApp()
    app.mainloop()


if __name__ == "__main__":
    main()
