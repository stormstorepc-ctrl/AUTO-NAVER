import base64
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app.purchasing import local_server as ls

ROOT = Path(__file__).resolve().parents[2]

NETSTAT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1100
  TCP    127.0.0.1:8765         0.0.0.0:0              ABHÖREN         4242
  TCP    127.0.0.1:8765         127.0.0.1:50123        ESTABLISHED     4242
  TCP    127.0.0.1:50123        127.0.0.1:8765         ESTABLISHED     9999
  TCP    127.0.0.1:87650        0.0.0.0:0              LISTENING       7777
"""


def test_netstat_listener_parse_is_locale_independent():
    assert ls.parse_netstat_listeners(NETSTAT) == {4242}


def test_password_rules():
    assert ls.read_password({}, prompt=lambda _: "longenough") == "longenough"
    assert ls.read_password({"PURCHASING_REVIEW_PASSWORD": "fromenv12"}, prompt=None) == "fromenv12"
    with pytest.raises(SystemExit):
        ls.read_password({}, prompt=lambda _: "short")


def test_stop_refuses_foreign_port_owner(tmp_path, monkeypatch):
    killed = []
    monkeypatch.setattr(ls, "listening_pids", lambda: {31337})
    monkeypatch.setattr(ls, "_terminate", lambda pid: killed.append(pid) or True)
    assert ls.stop(tmp_path / "state.json") == 1
    assert killed == []


def test_stop_ignores_stale_state_from_reused_pid(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    me = ls.process_identity(os.getpid())
    state.write_text(json.dumps({"pid": os.getpid(), "start": me["start"] + 1, "image": me["image"]}))
    killed = []
    monkeypatch.setattr(ls, "listening_pids", lambda: set())
    monkeypatch.setattr(ls, "_terminate", lambda pid: killed.append(pid) or True)
    assert ls.stop(state) == 0
    assert killed == [] and not state.exists()


def test_batch_files_avoid_powershell_and_signed_exit_code_trap():
    for name in ("purchasing_install.bat", "purchasing_start.bat", "purchasing_stop.bat", "purchasing_weekly.bat"):
        raw = (ROOT / name).read_bytes()
        assert raw.count(b"\n") == raw.count(b"\r\n"), f"{name} must use CRLF line endings"
        text = "\n".join(line for line in raw.decode("utf-8").lower().splitlines()
                         if not line.lstrip().startswith("rem "))
        assert "powershell" not in text and ".ps1" not in text, name
        assert "if errorlevel" not in text, f"{name}: negative py.exe codes pass 'if errorlevel 1'"
    assert not list(ROOT.glob("purchasing_*.ps1"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX process control path")
def test_start_and_stop_real_server(tmp_path):
    with socket.socket() as s:
        if s.connect_ex((ls.HOST, ls.PORT)) == 0:
            pytest.skip("port 8765 is in use")
    secret = "s3cret-pass-xyz"
    env = {**os.environ, "PURCHASING_REVIEW_PASSWORD": secret, "PURCHASING_DB": str(tmp_path / "p.db")}
    proc = subprocess.Popen([sys.executable, "-m", "app.purchasing.local_server", "start"], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(100):
            if ls.STATE_FILE.exists() and ls.state_is_live(ls.read_state()):
                with socket.socket() as s:
                    if s.connect_ex((ls.HOST, ls.PORT)) == 0:
                        break
            time.sleep(0.1)
        else:
            pytest.fail("server did not start")
        assert secret not in ls.STATE_FILE.read_text()
        with pytest.raises(urllib.error.HTTPError) as unauth:
            urllib.request.urlopen(f"http://{ls.HOST}:{ls.PORT}/")
        assert unauth.value.code == 401
        token = base64.b64encode(f"reviewer:{secret}".encode()).decode()
        req = urllib.request.Request(f"http://{ls.HOST}:{ls.PORT}/", headers={"Authorization": f"Basic {token}"})
        assert urllib.request.urlopen(req).status == 200
        stop = subprocess.run([sys.executable, "-m", "app.purchasing.local_server", "stop"], cwd=ROOT,
                              capture_output=True, text=True)
        assert stop.returncode == 0, stop.stderr
        assert proc.wait(timeout=10) in (0, -15)  # uvicorn re-raises SIGTERM after a clean shutdown
        assert not ls.STATE_FILE.exists()
        output = proc.stdout.read()
        assert secret not in output and secret not in stop.stdout + stop.stderr
    finally:
        if proc.poll() is None:
            proc.kill()
