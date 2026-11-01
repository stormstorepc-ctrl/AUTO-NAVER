"""Auth regression checks. Run: python -m unittest discover -s tests -v"""
import importlib.util
import pathlib
import sys
import time
import types
import unittest
from unittest.mock import patch

SETTINGS = types.SimpleNamespace(
    admin_username="storm_operator",
    admin_password="test-only-strong-password",
    secret_key="test-secret-0123456789abcdef0123456789abcdef"
)
fake_app = types.ModuleType("app")
fake_app.__path__ = [str(pathlib.Path(__file__).resolve().parents[1] / "app")]
fake_settings = types.ModuleType("app.settings")
fake_settings.settings = SETTINGS
with patch.dict(sys.modules, {"app": fake_app, "app.settings": fake_settings}):
    spec = importlib.util.spec_from_file_location(
        "app.admin_auth", pathlib.Path(__file__).resolve().parents[1] / "app" / "admin_auth.py")
    auth = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(auth)

class AdminAuthTests(unittest.TestCase):
    def test_signed_cookie_accepted(self):
        self.assertTrue(auth.verify_session(auth.issue_session()))

    def test_plain_ok_rejected(self):
        self.assertFalse(auth.verify_session("ok"))

    def test_tampered_cookie_rejected(self):
        token = auth.issue_session()
        self.assertFalse(auth.verify_session(token[:-1] + ("a" if token[-1] != "a" else "b")))

    def test_expired_cookie_rejected(self):
        with patch.object(auth.time, "time", return_value=100000):
            token = auth.issue_session()
        with patch.object(auth.time, "time", return_value=100000 + auth.SESSION_MAX_AGE + 1):
            self.assertFalse(auth.verify_session(token))

    def test_insecure_defaults_rejected(self):
        with patch.object(SETTINGS, "admin_password", "ADMIN"):
            self.assertFalse(auth.valid_credentials("storm_operator", "ADMIN"))
            self.assertFalse(auth.verify_session(auth.issue_session()))

    def test_credentials(self):
        self.assertTrue(auth.valid_credentials("storm_operator", "test-only-strong-password"))
        self.assertFalse(auth.valid_credentials("storm_operator", "wrong"))

if __name__ == "__main__":
    unittest.main()
