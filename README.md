# OopsieFS

OopsieFS is a Linux desktop utility and OS class project that combines:

- event-driven file activity tracking,
- undoable file history,
- read-only FUSE portal views, and
- local-network file transfer using short receiver codes.

The project is intentionally built in user space so the operating-system ideas
are visible without modifying the Linux kernel.

## Why OopsieFS Exists

Normal filesystems remember the current state of files, but everyday users often
care about recent activity:

- What changed recently?
- Which file was deleted?
- Can I undo a tracked file operation?
- Can I send this file to another laptop without cloud storage?

OopsieFS answers those questions through a desktop app, a metadata store, a
FUSE mount, and a lightweight LAN transfer layer.

> Status: OopsieFS is an educational alpha. It is useful for demos and learning
> OS concepts, but it is not a backup system and should not be trusted as the
> only copy of important files.

## Features

- **Lightweight file tracking**
  - Uses Linux `inotify` events instead of recursively scanning the whole laptop.
  - Watches common user folders such as Documents, Downloads, Pictures, Music,
    Videos, Desktop, and Academics when they exist.

- **Latest Changed view**
  - Shows recently created or modified files recorded by the watcher.

- **Command History**
  - Records actions performed through OopsieFS.
  - Supports undo for selected tracked operations.

- **Deleted Files**
  - Tracks files deleted through OopsieFS.
  - Can mark externally deleted indexed files as deleted.

- **Version History**
  - Creates snapshots before OopsieFS-managed edits/deletes.
  - Allows restoring previous versions.

- **FUSE portal mount**
  - Exposes metadata-backed virtual folders:
    - `Latest Changed`
    - `Deleted Files`
    - `Version History`
    - `All Files`

- **Code-based LAN transfer**
  - Receiver generates a six-digit code.
  - Sender enters the code and sends a selected file over the same local network.
  - No cloud account or external server required.

## Screens You Get

- `Latest Changed`: recent files captured by `inotify` or manual indexing.
- `Command History`: OopsieFS operations, including reversible actions.
- `Deleted Files`: files moved into recovery storage by OopsieFS.
- `Version History`: files with restorable snapshots.
- `All Files`: active indexed files.
- `File Transfer`: receive with a short code or send the selected file.

## Project Structure

```text
OopsieFS/
├── oopsiefs_app.py        # Tkinter desktop app
├── oopsiefs_core.py       # metadata store, snapshots, undo operations
├── oopsiefs_config.py     # paths and environment configuration
├── oopsiefs_fuse.py       # read-only FUSE portal filesystem
├── oopsiefs_transfer.py   # LAN send/receive code transfer
├── oopsiefs_watcher.py    # Linux inotify watcher
├── requirements.txt       # Python dependency list
├── tests/                 # unit/integration tests
├── .github/workflows/     # CI
├── CONTRIBUTING.md
├── CHANGELOG.md
├── SECURITY.md
├── LICENSE
└── README.md
```

## Requirements

Tested on Linux.

Minimum system requirements:

- Python 3
- `python3-venv`
- Tkinter support for Python

On Ubuntu/Debian:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-tk
```

For the optional FUSE portal mount:

```bash
sudo apt install fuse3 libfuse2t64
```

`fusepy` uses the FUSE2 ABI, so `libfuse2t64` is required on Ubuntu 24.04.

## Quick Start

```bash
git clone https://github.com/inianexe/OopsieFS.git
cd OopsieFS
chmod +x install.sh
./install.sh
oopsiefs
```

You can also launch it directly without installing a menu entry:

```bash
./run_oopsiefs.sh
```

The first launch creates a local `.venv` and installs Python dependencies
automatically.

### Python Package Mode

For development, install it as an editable package:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
.venv/bin/oopsiefs
```

## Running the Desktop App

The app opens immediately and starts an `inotify` watcher in the background.
It does **not** recursively scan `/` on startup.

Default watched folders:

- `~/Desktop`
- `~/Documents`
- `~/Downloads`
- `~/Pictures`
- `~/Videos`
- `~/Music`
- `~/Academics`

Only folders that exist are watched.

### Watch Specific Folders

Use `OOPSIEFS_WATCH_ROOTS` with colon-separated paths:

```bash
OOPSIEFS_WATCH_ROOTS="$HOME/Documents:$HOME/Downloads" python3 oopsiefs_app.py
```

### Change Metadata Location

By default, metadata is stored in:

```text
~/.local/share/oopsiefs
```

Override it:

```bash
OOPSIEFS_STORE=/path/to/oopsiefs-store python3 oopsiefs_app.py
```

### Manual Recent Index

The `Index recent files` button performs a bounded manual index of watched
folders only. It does not scan the whole laptop.

Default window: 5 minutes.

Change it:

```bash
OOPSIEFS_SCAN_WINDOW_MINUTES=10 python3 oopsiefs_app.py
```

## Using the App

1. Start the app.
2. Create, edit, or delete a file inside a watched folder.
3. Wait a second or two for the watcher event.
4. Open `Latest Changed` to see recent activity.
5. Use `Command History` to inspect tracked actions.
6. Use `Deleted Files` to restore supported deleted files.
7. Use `Version History` to restore snapshots created by OopsieFS operations.

### What Is Undoable?

| Action | Undo behavior |
| --- | --- |
| Tracked edit | Restores the pre-edit snapshot |
| Soft delete | Restores the deleted file from recovery storage |
| Restore deleted file | Moves the restored file back into recovery storage |
| Restore version | Restores the version that was active before the restore |
| External watcher event | Logged only, not undoable |
| Send file | Logged only, not undoable |

## FUSE Portal Mount

Install optional FUSE system packages first:

```bash
sudo apt install fuse3 libfuse2t64
```

Start the mount:

```bash
oopsiefs-fuse
```

In another terminal:

```bash
ls OopsieFS_Mount
ls "OopsieFS_Mount/Latest Changed"
ls "OopsieFS_Mount/All Files"
```

Unmount:

```bash
fusermount3 -u OopsieFS_Mount
```

The FUSE mount is read-only. It displays metadata already recorded by the app
or by manual indexing. It does not trigger a recursive scan.

## LAN File Transfer

Receiver:

1. Open `File Transfer`.
2. Click `Start receiving`.
3. Share the six-digit code.

Sender:

1. Select a file in OopsieFS.
2. Open `File Transfer`.
3. Enter the receiver code.
4. Click `Send selected file`.

Received files are saved under:

```text
~/OopsieFS_Received/Received/
```

The sender and receiver must be on the same local network. OopsieFS uses UDP
discovery and an HTTP upload protected by the short receiver code.

## Testing

Run the full local smoke suite:

```bash
make smoke
```

Or run tests directly:

```bash
python3 -m unittest discover -s tests -v
```

The tests cover metadata indexing, snapshots, undo behavior, delete/restore, and
code-based LAN transfer using local dynamic ports.

## Environment Variables

| Variable | Purpose |
| --- | --- |
| `OOPSIEFS_WATCH_ROOTS` | Colon-separated list of watched folders |
| `OOPSIEFS_STORE` | Metadata/snapshot storage directory |
| `OOPSIEFS_SCAN_WINDOW_MINUTES` | Manual recent-index window |
| `OOPSIEFS_SCAN_WINDOW_SECONDS` | Manual recent-index window in seconds |
| `OOPSIEFS_TRACK_ROOT` | Advanced root used for path mapping/FUSE tests |
| `OOPSIEFS_MOUNT` | FUSE mount directory |

## Uninstall

Remove the desktop launcher and terminal commands:

```bash
./uninstall.sh
```

Runtime metadata is preserved at:

```text
~/.local/share/oopsiefs
```

## OS Concepts Demonstrated

- Filesystem event monitoring with `inotify`
- Metadata indexing
- Versioned file snapshots
- Soft delete/recovery
- Undoable command history
- FUSE virtual filesystem views
- UDP discovery and HTTP file transfer over LAN
- User-space OS tooling design

## Limitations

- OopsieFS is a prototype, not a backup system.
- It only snapshots files touched by OopsieFS-managed operations.
- It does not monitor every system directory.
- External deletes can be detected only for files already indexed.
- LAN transfer works on the same local network; it is not an internet relay.
- LAN transfer is not end-to-end encrypted.

## Quick Demo Script

```bash
mkdir -p "$HOME/Documents/OopsieDemo"
python3 oopsiefs_app.py
```

In another terminal:

```bash
echo "hello" > "$HOME/Documents/OopsieDemo/demo.txt"
echo "updated" >> "$HOME/Documents/OopsieDemo/demo.txt"
```

Return to the app and open `Latest Changed`.

## License

MIT License. See [LICENSE](LICENSE).
