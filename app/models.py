"""SQLAlchemy models — the multi-tenant data model from the architecture doc."""
import secrets
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def _pub(prefix: str, n: int = 20) -> str:
    return f"{prefix}_{secrets.token_hex(n // 2)}"


class Partner(db.Model):
    __tablename__ = "partners"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160))
    webhook_url = db.Column(db.String(400))          # partner's own result sink
    status = db.Column(db.String(20), default="active")   # active | suspended
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    users = db.relationship("User", backref="partner", cascade="all, delete-orphan")
    api_keys = db.relationship("ApiKey", backref="partner", cascade="all, delete-orphan")
    payments = db.relationship("Payment", backref="partner", cascade="all, delete-orphan")


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    partner_id = db.Column(db.Integer, db.ForeignKey("partners.id"))   # null => admin
    email = db.Column(db.String(160), unique=True, nullable=False)
    password_hash = db.Column(db.String(300), nullable=False)
    role = db.Column(db.String(20), default="partner")    # admin | partner
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class ApiKey(db.Model):
    __tablename__ = "api_keys"
    id = db.Column(db.Integer, primary_key=True)
    partner_id = db.Column(db.Integer, db.ForeignKey("partners.id"), nullable=False)
    label = db.Column(db.String(80), default="default")
    prefix = db.Column(db.String(24))        # shown in UI, e.g. "prt_live_8f2c…"
    key_hash = db.Column(db.String(80), unique=True, nullable=False)  # sha256 hex
    last_used_at = db.Column(db.DateTime)
    revoked_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def active(self) -> bool:
        return self.revoked_at is None


class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(40), unique=True, default=lambda: _pub("pay"))
    partner_id = db.Column(db.Integer, db.ForeignKey("partners.id"), nullable=False)

    reference = db.Column(db.String(120))        # partner's own order id
    title = db.Column(db.String(160))
    amount = db.Column(db.String(32), nullable=False)
    currency = db.Column(db.String(8), default="DJF")
    customer_ref = db.Column(db.String(120))

    merch_order_id = db.Column(db.String(40), unique=True)   # maps to D-Money
    prepay_id = db.Column(db.String(80))
    trade_no = db.Column(db.String(80))
    status = db.Column(db.String(16), default="PENDING")  # PENDING|SUCCESS|FAILED|CLOSED
    checkout_url = db.Column(db.Text)
    return_url = db.Column(db.String(400))
    raw_notify = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime)

    events = db.relationship("WebhookEvent", backref="payment",
                             cascade="all, delete-orphan")

    def to_api(self) -> dict:
        return {
            "payment_id": self.public_id,
            "reference": self.reference,
            "amount": self.amount,
            "currency": self.currency,
            "status": self.status,
            "trade_no": self.trade_no,
            "checkout_url": self.checkout_url,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
            "paid_at": self.paid_at.isoformat() + "Z" if self.paid_at else None,
        }


class WebhookEvent(db.Model):
    __tablename__ = "webhook_events"
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"))
    dedupe_key = db.Column(db.String(80), unique=True)      # merch_order_id:status
    signature_verified = db.Column(db.Boolean, default=False)
    verify_method = db.Column(db.String(20))
    payload = db.Column(db.Text)
    received_at = db.Column(db.DateTime, default=datetime.utcnow)
