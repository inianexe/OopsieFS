.PHONY: test lint smoke

PYTHON ?= python3

test:
	$(PYTHON) -m unittest discover -s tests -v

lint:
	$(PYTHON) -m py_compile oopsiefs_config.py oopsiefs_core.py oopsiefs_app.py oopsiefs_transfer.py oopsiefs_watcher.py

smoke: lint test
