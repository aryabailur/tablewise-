#!/usr/bin/env python3
"""Run the Tablewise API (FastAPI :8000) and web app (Vite :5173) together.

    python scripts/dev.py        # Ctrl+C stops both

Stdlib only. Uses backend/.venv's python, so run `cd backend && uv sync` first.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
IS_WIN = os.name == "nt"

if IS_WIN:
    os.system("")  # enable ANSI colours in the classic Windows console
try:
    sys.stdout.reconfigure(errors="replace")  # never crash on odd bytes from children
except AttributeError:
    pass

USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
COLORS = {"api": "\033[36m", "web": "\033[35m", "dev": "\033[33m"}
_print_lock = threading.Lock()


def say(tag: str, line: str) -> None:
    prefix = f"[{tag}]"
    if USE_COLOR:
        prefix = f"{COLORS.get(tag, '')}{prefix}\033[0m"
    with _print_lock:
        print(f"{prefix} {line}", flush=True)


def venv_python() -> Path:
    return BACKEND / ".venv" / ("Scripts/python.exe" if IS_WIN else "bin/python")


def npm() -> str:
    exe = shutil.which("npm.cmd" if IS_WIN else "npm")
    if not exe:
        say("dev", "npm not found on PATH - install Node.js 20+")
        sys.exit(1)
    return exe


def start(tag: str, cmd: list[str], cwd: Path) -> subprocess.Popen:
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    if USE_COLOR:
        env.setdefault("FORCE_COLOR", "1")
    kwargs: dict = {}
    if IS_WIN:
        # Own process group: the console's Ctrl+C reaches only us (no "Terminate batch job?" prompt).
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)

    def pump() -> None:
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, b""):
            say(tag, raw.decode("utf-8", errors="replace").rstrip())

    threading.Thread(target=pump, daemon=True).start()
    return proc


def stop(proc: subprocess.Popen) -> None:
    """Terminate the whole process tree (uvicorn's reload worker, npm -> node/vite)."""
    if proc.poll() is not None:
        return
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=8)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            if IS_WIN:
                proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main() -> int:
    py = venv_python()
    if not py.exists():
        say("dev", f"{py} not found - run `cd backend && uv sync` (or `make setup`) first")
        return 1

    procs: dict[str, subprocess.Popen] = {
        "api": start("api", [str(py), "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000"], BACKEND),
    }

    if (FRONTEND / "package.json").exists():
        if not (FRONTEND / "node_modules").exists():
            say("dev", "frontend/node_modules missing - running npm install")
            subprocess.run([npm(), "install"], cwd=FRONTEND, check=False)
        procs["web"] = start("web", [npm(), "run", "dev"], FRONTEND)
    else:
        say("dev", "frontend/ not found - starting the API only")

    say("dev", "API http://localhost:8000  |  Web http://localhost:5173  |  Ctrl+C to stop")
    code = 0
    try:
        while True:
            for tag, p in procs.items():
                if p.poll() is not None:
                    say("dev", f"{tag} exited with code {p.returncode} - shutting down")
                    code = p.returncode or 1
                    raise KeyboardInterrupt
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        say("dev", "stopping...")
        for p in procs.values():
            stop(p)
    return code


if __name__ == "__main__":
    sys.exit(main())
