"""Partner-facing REST API (v1). Auth = partner API key.

This is the ENTIRE surface a partner integrates against:
    POST /api/v1/payments        -> create a payment, get a checkout_url
    GET  /api/v1/payments/<id>   -> poll a payment's status
    GET  /api/v1/payments        -> list the partner's payments
"""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, g, jsonify, request

from ..dmoney import DMoneyClient, DMoneyError
from ..models import Payment, db
from ..security import require_api_key

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")

ALLOWED_CURRENCIES = {"DJF", "USD", "EUR"}


def _client() -> DMoneyClient:
    return DMoneyClient(current_app.config)


@api_bp.post("/payments")
@require_api_key
def create_payment():
    data = request.get_json(silent=True) or {}

    # --- validate ---
    amount_raw = str(data.get("amount", "")).strip()
    try:
        amount = Decimal(amount_raw)
        # Reject NaN/Infinity (they slip past a plain `<= 0` check) and non-positive.
        if not amount.is_finite() or amount <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        return jsonify(error="invalid_amount",
                       message="`amount` must be a positive decimal string, e.g. \"30.00\"."), 400

    currency = (data.get("currency") or "DJF").upper()
    if currency not in ALLOWED_CURRENCIES:
        return jsonify(error="invalid_currency",
                       message=f"`currency` must be one of {sorted(ALLOWED_CURRENCIES)}."), 400

    reference = (data.get("reference") or "").strip() or None
    title = (data.get("title") or "Payment").strip()[:160]
    customer_ref = (data.get("customer_ref") or "").strip() or None
    return_url = (data.get("return_url") or "").strip() or None
    amount_str = f"{amount:.2f}"

    # --- idempotency on the partner's own reference ---
    if reference:
        existing = Payment.query.filter_by(
            partner_id=g.partner.id, reference=reference
        ).first()
        if existing:
            return jsonify(**existing.to_api(), idempotent=True), 200

    # --- create the order + signed checkout URL ---
    client = _client()
    merch_order_id = client.new_order_id()
    try:
        prepay_id, checkout_url = client.create_checkout(
            merch_order_id, amount_str, title, currency, redirect_url=return_url
        )
    except DMoneyError as exc:
        return jsonify(error="gateway_error", message=str(exc)), 502

    pay = Payment(
        partner_id=g.partner.id, reference=reference, title=title,
        amount=amount_str, currency=currency, customer_ref=customer_ref,
        merch_order_id=merch_order_id, prepay_id=prepay_id,
        status="PENDING", checkout_url=checkout_url, return_url=return_url,
    )
    db.session.add(pay)
    db.session.commit()

    body = pay.to_api()
    body["expires_at"] = (datetime.utcnow() + timedelta(minutes=120)).isoformat() + "Z"
    return jsonify(**body), 201


@api_bp.get("/payments/<public_id>")
@require_api_key
def get_payment(public_id):
    pay = Payment.query.filter_by(
        public_id=public_id, partner_id=g.partner.id
    ).first()
    if not pay:
        return jsonify(error="not_found", message="No such payment."), 404
    return jsonify(**pay.to_api())


@api_bp.get("/payments")
@require_api_key
def list_payments():
    page = max(1, request.args.get("page", 1, type=int))
    per = min(100, max(1, request.args.get("per_page", 20, type=int)))
    q = Payment.query.filter_by(partner_id=g.partner.id)
    status = request.args.get("status")
    if status:
        q = q.filter_by(status=status.upper())
    q = q.order_by(Payment.created_at.desc())
    items = q.paginate(page=page, per_page=per, error_out=False)
    return jsonify(
        page=page, per_page=per, total=items.total,
        data=[p.to_api() for p in items.items],
    )
