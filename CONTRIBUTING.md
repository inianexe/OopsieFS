# Contributing

OopsieFS is a student OS project, so contributions should keep the code easy to
read, demo, and explain.

## Development Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Run syntax checks:

```bash
python3 -m py_compile oopsiefs_config.py oopsiefs_core.py oopsiefs_app.py oopsiefs_transfer.py oopsiefs_watcher.py
.venv/bin/python -m py_compile oopsiefs_fuse.py
```

## Guidelines

- Keep runtime data out of git.
- Prefer standard-library implementations when practical.
- Keep filesystem operations safe and explicit.
- Document OS concepts when adding new features.
