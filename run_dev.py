#!/usr/bin/env python3
"""
Debug / local entry point: start PostGIS (Docker) + FastAPI web UI/backend.

Usage (from repo root):
  python run_dev.py              # full mode (default)
  python run_dev.py --database   # database-only dashboard mode (--db)

Opens: http://localhost:8000

Reload (Windows-safe): parent watches backend/*.py and restarts a plain uvicorn
subprocess via taskkill — never uses `uvicorn --reload` (its Ctrl+C broadcast
was stopping the whole server on every save).
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
DEFAULT_HOST = os.getenv("DEV_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("DEV_PORT", "8000"))


def log(msg: str) -> None:
    print(f"[wardrivrr] {msg}", flush=True)


def disable_windows_quick_edit() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        h_in = kernel32.GetStdHandle(-10)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(h_in, ctypes.byref(mode)):
            return
        ENABLE_EXTENDED_FLAGS = 0x0080
        ENABLE_QUICK_EDIT = 0x0040
        kernel32.SetConsoleMode(h_in, mode.value | ENABLE_EXTENDED_FLAGS)
        kernel32.SetConsoleMode(
            h_in, (mode.value | ENABLE_EXTENDED_FLAGS) & ~ENABLE_QUICK_EDIT
        )
    except Exception:
        pass


def ensure_venv_hint() -> None:
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    venv_python = ROOT / "venv" / "Scripts" / "python.exe"
    if not in_venv and venv_python.exists():
        log(f"Tip: use the project venv → {venv_python} run_dev.py")


def docker_compose(*args: str, timeout_s: float | None = 120.0) -> None:
    if not shutil.which("docker"):
        sys.exit("Docker not found on PATH. Install Docker Desktop and retry.")
    cmd = ["docker", "compose", *args]
    log(" ".join(cmd))
    try:
        subprocess.run(cmd, cwd=ROOT, check=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        sys.exit(f"Docker command timed out after {timeout_s:.0f}s: {' '.join(cmd)}")


def wait_for_postgis(timeout_s: float = 60.0) -> None:
    log("Waiting for PostGIS to become healthy…")
    user = os.getenv("DB_USER", "explorer")
    dbname = os.getenv("DB_NAME", "wardriving")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        health = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                "wardrivrr_postgis",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        status = (health.stdout or "").strip().lower()
        if status == "healthy":
            log("PostGIS is healthy.")
            return
        probe = subprocess.run(
            [
                "docker",
                "exec",
                "wardrivrr_postgis",
                "pg_isready",
                "-U",
                user,
                "-d",
                dbname,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if probe.returncode == 0:
            log("PostGIS accepts connections.")
            return
        time.sleep(1.5)
    sys.exit("PostGIS did not become ready in time. Check: docker compose logs postgis")


def start_postgis() -> None:
    docker_compose("up", "postgis", "-d")
    wait_for_postgis()


def under_debugger() -> bool:
    return sys.gettrace() is not None or os.getenv("WARDIVRR_DEBUG") == "1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start wardrivrr PostGIS + API. Full mode by default; --database for home-server dashboard."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--full",
        action="store_const",
        const="full",
        dest="mode",
        help="Full stack semantics (default): GPS/Kismet/routing expected in status UI",
    )
    mode.add_argument(
        "--database",
        "--db",
        action="store_const",
        const="database",
        dest="mode",
        help="Database mode: only PostGIS + API; GPS/Kismet/routing show as N/A (gray)",
    )
    parser.set_defaults(mode=None)
    return parser.parse_args(argv)


def kill_process_tree(pid: int) -> None:
    if pid <= 0:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
            timeout=30,
        )
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.time() + 4
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.15)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def _wait_port_free(host: str, port: int, timeout_s: float = 8.0) -> None:
    import socket

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            try:
                if sock.connect_ex((host, port)) != 0:
                    return
            except OSError:
                return
        time.sleep(0.15)


def spawn_uvicorn(env: dict) -> subprocess.Popen:
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        DEFAULT_HOST,
        "--port",
        str(DEFAULT_PORT),
        "--app-dir",
        str(BACKEND),
        "--log-level",
        "info",
    ]
    kwargs: dict = {
        "cwd": str(BACKEND),
        "env": env,
    }
    if sys.platform == "win32":
        # Own process group so taskkill /T can tear the tree down without
        # broadcasting Ctrl+C to this console (which stops run.bat).
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(cmd, **kwargs)


def _py_watch_filter(change, path: str) -> bool:
    p = path.replace("\\", "/")
    name = Path(p).name
    if not name.endswith(".py"):
        return False
    if name.startswith("_"):
        return False
    if "/__pycache__/" in f"/{p}/":
        return False
    return True


def start_api(mode: str) -> int:
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        sys.exit(
            "uvicorn not installed. Run:\n"
            f"  {sys.executable} -m pip install -r backend/requirements.txt"
        )

    use_reload = not under_debugger()
    log(f"Deployment mode: {mode}")
    log(
        f"Starting API on http://{DEFAULT_HOST}:{DEFAULT_PORT}"
        f" (reload={'on' if use_reload else 'off — debugger attached'})"
    )
    log("UI: /  Database: /database  Status: /status  Settings: /settings  Docs: /docs")
    log("Ctrl+C stops for good.")

    env = os.environ.copy()
    env["WARDIVRR_MODE"] = mode
    env["PYTHONUNBUFFERED"] = "1"

    if not use_reload:
        proc = spawn_uvicorn(env)
        try:
            return int(proc.wait() or 0)
        except KeyboardInterrupt:
            log("Stopping API…")
            kill_process_tree(proc.pid)
            log("Stopped.")
            return 0

    try:
        from watchfiles import watch
    except ImportError:
        log("watchfiles missing — running without auto-reload")
        proc = spawn_uvicorn(env)
        try:
            return int(proc.wait() or 0)
        except KeyboardInterrupt:
            kill_process_tree(proc.pid)
            log("Stopped.")
            return 0

    log(f"Watching {BACKEND} for .py changes…")
    proc = spawn_uvicorn(env)
    min_backoff = 1.0
    max_backoff = 3.0
    backoff = min_backoff

    try:
        for changes in watch(
            BACKEND,
            watch_filter=_py_watch_filter,
            debounce=1000,
            step=50,
            rust_timeout=800,
            yield_on_timeout=True,
            raise_interrupt=False,
        ):
            died = proc.poll() is not None
            if changes:
                names = sorted({Path(p).name for _, p in changes})[:5]
                extra = "" if len(changes) <= 5 else f" (+{len(changes) - 5})"
                log(f"Code change — restarting API ({', '.join(names)}{extra})…")
                kill_process_tree(proc.pid)
                try:
                    proc.wait(timeout=8)
                except Exception:
                    kill_process_tree(proc.pid)
                _wait_port_free(DEFAULT_HOST, DEFAULT_PORT)
                proc = spawn_uvicorn(env)
                backoff = min_backoff
            elif died:
                code = proc.returncode
                log(f"API exited (code {code}); restarting in {backoff:.0f}s…")
                try:
                    time.sleep(backoff)
                except KeyboardInterrupt:
                    break
                backoff = min(max_backoff, backoff + 1.0)
                _wait_port_free(DEFAULT_HOST, DEFAULT_PORT)
                proc = spawn_uvicorn(env)
    except KeyboardInterrupt:
        pass
    finally:
        log("Stopping API…")
        kill_process_tree(proc.pid)
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        log("Stopped.")
    return 0


def main(argv: list[str] | None = None) -> int:
    disable_windows_quick_edit()
    args = parse_args(argv)
    mode = args.mode or os.getenv("WARDIVRR_MODE", "full").strip().lower()
    if mode not in {"full", "database"}:
        sys.exit(f"Invalid WARDIVRR_MODE={mode!r}; use full or database")
    ensure_venv_hint()
    start_postgis()
    return start_api(mode)


if __name__ == "__main__":
    raise SystemExit(main())
