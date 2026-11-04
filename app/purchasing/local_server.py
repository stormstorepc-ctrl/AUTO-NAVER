"""Start and stop the local review server without PowerShell script files.

purchasing_start.bat / purchasing_stop.bat call this module with the virtual
environment's python.exe. Windows script-signing rules (AllSigned, RemoteSigned
with a downloaded-ZIP mark) apply to .ps1 files, not to python.exe, so the
review server can start without changing the machine's execution policy.

The password is read with getpass (no echo) and handed to the app in memory.
It is never put in an environment variable, a file, or the console output.
The state file only records the server process identity so that stop can
refuse to touch any other process.
"""
from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8765
MIN_PASSWORD = 8
ROOT = Path(__file__).resolve().parents[2]
STATE_FILE = ROOT / ".purchasing_server.json"


# --- process identity -------------------------------------------------------

def _windows_identity(pid: int):
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) or exit_code.value != 259:  # STILL_ACTIVE
            return None
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                        ctypes.byref(kernel), ctypes.byref(user)):
            return None
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return None
        return {"start": (created.dwHighDateTime << 32) | created.dwLowDateTime, "image": buf.value}
    finally:
        kernel32.CloseHandle(handle)


def _posix_identity(pid: int):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        image = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return None
    fields = stat.rsplit(")", 1)[1].split()
    if fields[0] == "Z":
        return None
    return {"start": int(fields[19]), "image": image}


def process_identity(pid: int):
    """Return {start, image} for a live process, or None. start guards against PID reuse."""
    return _windows_identity(pid) if os.name == "nt" else _posix_identity(pid)


# --- port owner -------------------------------------------------------------

def parse_netstat_listeners(text: str, host: str = HOST, port: int = PORT) -> set[int]:
    """PIDs listening on host:port in `netstat -ano -p TCP` output.

    The state column is localized on some Windows languages, so a listener is
    recognised by its foreign address 0.0.0.0:0 instead of the word LISTENING.
    """
    pids = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[1] == f"{host}:{port}" \
                and parts[2] == "0.0.0.0:0" and parts[-1].isdigit():
            pids.add(int(parts[-1]))
    return pids


def listening_pids():
    """PIDs on 127.0.0.1:8765, or None when it cannot be determined on this OS."""
    if os.name != "nt":
        return None
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, errors="replace")
    if out.returncode != 0:
        return None
    return parse_netstat_listeners(out.stdout)


# --- state file -------------------------------------------------------------

def read_state(path: Path = STATE_FILE):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"pid": int(data["pid"]), "start": int(data["start"]), "image": str(data["image"])}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def state_is_live(state) -> bool:
    if not state:
        return False
    ident = process_identity(state["pid"])
    return bool(ident) and ident["start"] == state["start"] and \
        os.path.normcase(ident["image"]) == os.path.normcase(state["image"])


# --- commands ---------------------------------------------------------------

def read_password(environ=os.environ, prompt=getpass.getpass) -> str:
    password = environ.get("PURCHASING_REVIEW_PASSWORD") or \
        prompt(f"Choose a local review password ({MIN_PASSWORD} or more characters): ")
    if len(password) < MIN_PASSWORD:
        raise SystemExit(f"Password must have at least {MIN_PASSWORD} characters.")
    return password


def start(state_path: Path = STATE_FILE) -> int:
    os.chdir(ROOT)
    if state_is_live(read_state(state_path)):
        print("The review server is already running. Run purchasing_stop.bat first.", file=sys.stderr)
        return 1
    password = read_password()
    # Import after the password check so a typo does not wait on FastAPI imports.
    import uvicorn
    from app.purchasing.store import Store
    from app.purchasing.web import create_app

    app = create_app(Store(os.environ.get("PURCHASING_DB", "purchasing.db")),
                     os.environ.get("PURCHASING_REVIEW_USER", "reviewer"), password)
    del password
    me = process_identity(os.getpid())
    if me:
        state_path.write_text(json.dumps({"pid": os.getpid(), **me}), encoding="utf-8")
    print(f"Open http://{HOST}:{PORT} in Chrome. Default username: reviewer. Press Ctrl+C to stop.", flush=True)
    try:
        server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT))
        server.run()
        return 0 if server.started else 1
    finally:
        if (read_state(state_path) or {}).get("pid") == os.getpid():
            state_path.unlink(missing_ok=True)


def _terminate(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True, errors="replace")
        return out.returncode == 0
    import signal
    os.kill(pid, signal.SIGTERM)
    return True


def stop(state_path: Path = STATE_FILE) -> int:
    state = read_state(state_path)
    live = state_is_live(state)
    listeners = listening_pids()
    if listeners is not None:
        others = listeners - ({state["pid"]} if live else set())
        if others:
            print(f"Port {PORT} belongs to a different process (PID {', '.join(map(str, sorted(others)))}). "
                  "Refusing to stop it.", file=sys.stderr)
            return 1
    if not live:
        if state:
            state_path.unlink(missing_ok=True)
        print("The review server is not running.")
        return 0
    if not _terminate(state["pid"]):
        print(f"Could not stop review server PID {state['pid']}.", file=sys.stderr)
        return 1
    state_path.unlink(missing_ok=True)
    print(f"Stopped purchasing review PID {state['pid']}.")
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["start"]:
        return start()
    if argv == ["stop"]:
        return stop()
    print("usage: python -m app.purchasing.local_server start|stop", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
