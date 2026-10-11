# Tablewise (Ember & Vine) - dev tasks.
# No make on Windows? Use the commands in README.md, or: python scripts/dev.py

BACKEND  := backend
FRONTEND := frontend

# Prefer uv when it is on PATH; otherwise fall back to a plain venv + pip.
UV := $(shell command -v uv 2>/dev/null)

ifeq ($(OS),Windows_NT)
  PYTHON      ?= python
  VENV_PY_REL := .venv/Scripts/python.exe
else
  PYTHON      ?= python3
  VENV_PY_REL := .venv/bin/python
endif

ifneq ($(UV),)
  BPY := uv run python
else
  BPY := $(VENV_PY_REL)
endif

.PHONY: help setup seed dev mcp build

help:
	@echo "make setup  - install backend deps (uv sync, or venv + pip) and frontend deps (npm install)"
	@echo "make seed   - create tables, demo bookings, and ingest knowledge/ into Chroma"
	@echo "make dev    - run API (:8000) + web (:5173) together via scripts/dev.py"
	@echo "make mcp    - run the MCP server (stdio)"
	@echo "make build  - production build of the frontend"

# pyproject.toml has no [build-system], so the pip fallback installs its dependency list
# (equivalent of `pip install -e .` without packaging the app).
setup:
ifneq ($(UV),)
	cd $(BACKEND) && uv sync
else
	@echo "uv not found - falling back to python -m venv + pip"
	cd $(BACKEND) && $(PYTHON) -m venv .venv
	cd $(BACKEND) && $(VENV_PY_REL) -m pip install --upgrade pip
	cd $(BACKEND) && $(VENV_PY_REL) -c "import subprocess, sys, tomllib; deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; sys.exit(subprocess.call([sys.executable, '-m', 'pip', 'install', *deps]))"
endif
	cd $(FRONTEND) && npm install

seed:
	cd $(BACKEND) && $(BPY) -m app.seed

dev:
	$(PYTHON) scripts/dev.py

mcp:
	cd $(BACKEND) && $(BPY) mcp_server.py

build:
	cd $(FRONTEND) && npm run build
