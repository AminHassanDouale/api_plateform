"""Authentication & authorization.

Two independent mechanisms:
  * API keys   -> machine-to-machine (partner backend calling /api/v1/*)
  * Sessions   -> humans logging into the dashboard / admin
No external auth library; just Werkzeug password hashing + Flask sessions.
"""
import hashlib
import secrets
from datetime import datetime
from functools import wraps

from flask import g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .models import ApiKey, User, db


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
def generate_api_key(env: str = "live"):
    """Return (full_key, prefix, key_hash). The full key is shown ONCE."""
    secret = secrets.token_urlsafe(32)
    full = f"prt_{env}_{secret}"
    prefix = full[:16] + "…"
    return full, prefix, hash_api_key(full)


def hash_api_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode()).hexdigest()


def _extract_key() -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-API-Key")


def require_api_key(f):
    """Guard partner API endpoints. Sets g.partner / g.api_key on success."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        key = _extract_key()
        if not key:
            return jsonify(error="missing_api_key",
                           message="Provide your key via 'Authorization: Bearer <key>'."), 401
        record = ApiKey.query.filter_by(key_hash=hash_api_key(key)).first()
        if not record or not record.active:
            return jsonify(error="invalid_api_key",
                           message="API key is invalid or revoked."), 401
        if record.partner.status != "active":
            return jsonify(error="partner_suspended",
                           message="This partner account is suspended."), 403
        record.last_used_at = datetime.utcnow()
        db.session.commit()
        g.partner = record.partner
        g.api_key = record
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Session login (dashboard / admin)
# ---------------------------------------------------------------------------
def hash_password(raw: str) -> str:
    return generate_password_hash(raw)


def verify_password(hash_: str, raw: str) -> bool:
    return check_password_hash(hash_, raw)


def login_user(user: User) -> None:
    session["user_id"] = user.id


def logout_user() -> None:
    session.pop("user_id", None)


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return db.session.get(User, uid)


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for("auth.login", next=request.path))
        if not user.is_admin:
            return "Forbidden — admin only", 403
        return f(*args, **kwargs)
    return wrapper
