"""Signed, time-limited administrator sessions (stdlib only)."""
import hashlib
import hmac
import secrets
import time
from .settings import settings

COOKIE = "stormpc_admin"
SESSION_MAX_AGE = 8 * 60 * 60

def configured():
    """Refuse insecure defaults rather than allow public admin access."""
    return bool(
        settings.admin_username and settings.admin_password
        and settings.admin_username != "ADMIN"
        and settings.admin_password != "ADMIN"
        and settings.secret_key and settings.secret_key != "change-me"
        and len(settings.secret_key) >= 32
    )

def valid_credentials(username, password):
    if not configured():
        return False
    return secrets.compare_digest(str(username), settings.admin_username) and secrets.compare_digest(
        str(password), settings.admin_password
    )

def _signature(timestamp, nonce):
    message = f"{timestamp}.{nonce}".encode("ascii")
    return hmac.new(settings.secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()

def issue_session():
    if not configured():
        raise RuntimeError("Configure ADMIN_USERNAME, ADMIN_PASSWORD and SECRET_KEY before enabling admin login.")
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    return f"{timestamp}.{nonce}.{_signature(timestamp, nonce)}"

def verify_session(value):
    if not configured() or not value or len(value) > 200:
        return False
    try:
        timestamp, nonce, signature = value.split(".")
        if not timestamp.isascii() or not timestamp.isdigit() or len(nonce) != 32 or len(signature) != 64:
            return False
        if any(c not in "0123456789abcdef" for c in nonce + signature):
            return False
        age = time.time() - int(timestamp)
        if age < -60 or age > SESSION_MAX_AGE:
            return False
        return hmac.compare_digest(_signature(timestamp, nonce), signature)
    except (ValueError, TypeError, AttributeError):
        return False

def is_admin(request):
    return verify_session(request.cookies.get(COOKIE))

def set_admin_cookie(response, request):
    response.set_cookie(
        COOKIE, issue_session(), max_age=SESSION_MAX_AGE,
        httponly=True, samesite="strict", secure=(request.url.scheme == "https"),
        path="/",
    )
