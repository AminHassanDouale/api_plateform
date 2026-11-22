"""Inbound D-Money notify webhook.

D-Money POSTs the payment result here. We verify the signature, update the
payment, record the event idempotently, optionally forward to the partner's own
webhook, and ACK with 200 fast.
"""
import json
from datetime import datetime

import requests
from flask import Blueprint, current_app, request

from ..dmoney import DMoneyClient
from ..models import Payment, WebhookEvent, db

webhook_bp = Blueprint("webhook", __name__)

# Paths D-Money may POST to (matches PG.py's NOTIFY_URL path + aliases).
NOTIFY_PATHS = ("/user/v1/payments/d-money/notify", "/notify", "/d-money/notify")

SUCCESS = {"SUCCESS", "PAID", "TRADE_SUCCESS", "COMPLETED"}
FAILURE = {"FAILED", "CLOSED", "CANCELLED", "TRADE_CLOSED"}


def _flatten(raw_body: bytes) -> dict:
    data = json.loads(raw_body.decode("utf-8"))
    biz = data.get("biz_content")
    if isinstance(biz, str):
        try:
            biz = json.loads(biz)
        except ValueError:
            biz = None
    if isinstance(biz, dict):
        merged = {**data, **biz}
        merged.pop("biz_content", None)
        return merged
    return data


def _normalize_status(raw: str) -> str:
    s = (raw or "").upper()
    if s in SUCCESS:
        return "SUCCESS"
    if s in FAILURE:
        return "CLOSED" if s in {"CLOSED", "TRADE_CLOSED", "CANCELLED"} else "FAILED"
    return "PENDING"


def _forward_to_partner(partner, payment):
    """Best-effort POST the result to the partner's own webhook_url."""
    if not partner.webhook_url:
        return
    try:
        requests.post(partner.webhook_url, json=payment.to_api(), timeout=5)
    except Exception as exc:                       # never let this affect our 200
        current_app.logger.warning("partner webhook failed: %s", exc)


def _handle(raw_body: bytes, signature: str):
    client = DMoneyClient(current_app.config)
    verified_with = client.verify_webhook(raw_body, signature)

    # Fail CLOSED: if strict mode is on and the signature didn't verify — whether
    # because it was wrong, absent, or no public key is loaded — reject. (Don't
    # gate this on `client.public_key`, or a missing key file silently disables it.)
    if current_app.config["DMONEY_STRICT_SIGNATURE"] and not verified_with:
        return {"code": "1", "msg": "signature verification failed"}, 401

    try:
        n = _flatten(raw_body)
    except Exception:
        return {"code": "1", "msg": "invalid json"}, 400

    merch_order_id = n.get("merch_order_id") or n.get("out_trade_no")
    status = _normalize_status(n.get("trade_status") or n.get("status"))
    dedupe_key = f"{merch_order_id or 'unknown'}:{status}"

    # Idempotency: a repeated notification is ACK'd but not re-applied.
    if WebhookEvent.query.filter_by(dedupe_key=dedupe_key).first():
        return {"code": "0", "msg": "SUCCESS"}, 200

    payment = Payment.query.filter_by(merch_order_id=merch_order_id).first() if merch_order_id else None

    event = WebhookEvent(
        payment_id=payment.id if payment else None,
        dedupe_key=dedupe_key,
        signature_verified=bool(verified_with),
        verify_method=verified_with,
        payload=raw_body.decode("utf-8", "replace"),
    )
    db.session.add(event)

    if payment and payment.status == "PENDING":
        payment.status = status
        payment.trade_no = n.get("trade_no") or payment.trade_no
        payment.raw_notify = event.payload
        if status == "SUCCESS":
            payment.paid_at = datetime.utcnow()
    db.session.commit()

    if payment and payment.partner:
        _forward_to_partner(payment.partner, payment)

    return {"code": "0", "msg": "SUCCESS"}, 200


@webhook_bp.route("/user/v1/payments/d-money/notify", methods=["POST"])
@webhook_bp.route("/notify", methods=["POST"])
@webhook_bp.route("/d-money/notify", methods=["POST"])
def notify():
    raw_body = request.get_data() or b""
    signature = request.headers.get(current_app.config["DMONEY_SIGNATURE_HEADER"], "")
    body, code = _handle(raw_body, signature)
    return body, code


@webhook_bp.get("/notify")
def notify_health():
    return {"status": "ok", "service": "d-money notify"}
