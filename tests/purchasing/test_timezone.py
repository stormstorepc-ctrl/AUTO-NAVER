import os
import subprocess
import sys


def test_cli_without_system_timezone_database(tmp_path):
    env = {**os.environ, 'PYTHONTZPATH': '', 'PURCHASING_DB': str(tmp_path / 'weekly.db')}
    result = subprocess.run([sys.executable, '-m', 'app.purchasing.cli', 'weekly-mock'],
                            env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    import json
    summary = json.loads(result.stdout)
    assert summary['jobs'] == 0 and summary['real_published'] == 0
