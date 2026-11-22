"""Create a test checkout (random order id) and print the links to try it.

    .venv/bin/python scripts/test_checkout.py

Reuses (or creates) a "Test Shop" partner, mints a fresh API key, creates one
PENDING payment through the real API, and prints the checkout URL plus the
customer return-page URL. In SIMULATE mode it also prints a ready-to-run curl
that stands in for D-Money confirming the payment.
"""
import random

from app import create_app
from app.models import db, ApiKey, Partner, Payment
from app.security import generate_api_key

app = create_app()
base = app.config["PLATFORM_BASE_URL"].rstrip("/")

with app.app_context():
    partner = Partner.query.filter_by(name="Test Shop").first()
    if not partner:
        partner = Partner(name="Test Shop", email="test@shop.local", status="active")
        db.session.add(partner)
        db.session.flush()
    full_key, prefix, key_hash = generate_api_key()
    db.session.add(ApiKey(partner_id=partner.id, prefix=prefix, key_hash=key_hash))
    db.session.commit()

    ref = f"TEST-ORDER-{random.randint(100000, 999999)}"
    resp = app.test_client().post(
        "/api/v1/payments",
        headers={"Authorization": f"Bearer {full_key}"},
        json={"amount": "250.00", "currency": "DJF", "reference": ref,
              "title": "Test checkout", "return_url": base + "/payment/return"},
    )
    body = resp.get_json()
    pid = body["payment_id"]
    moid = Payment.query.filter_by(public_id=pid).first().merch_order_id

    bar = "=" * 72
    print(bar)
    print("  TEST CHECKOUT CREATED")
    print(bar)
    print(f"  reference (order id) : {ref}")
    print(f"  payment_id           : {pid}")
    print(f"  status               : {body['status']}")
    print(f"  API key (Test Shop)  : {full_key}")
    print()
    print("  1) checkout_url  — where the customer pays:")
    print(f"     {body['checkout_url']}")
    print()
    print("  2) return page   — open in your browser (shows PENDING, auto-refreshes):")
    print(f"     {base}/payment/return?payment_id={pid}")
    print()
    print("  3) simulate D-Money confirming the payment, then refresh the page:")
    print(f"     curl -s -X POST {base}/notify -H 'Content-Type: application/json' \\")
    print(f"       -d '{{\"merch_order_id\":\"{moid}\",\"trade_status\":\"SUCCESS\",\"trade_no\":\"DM-TEST\"}}'")
    print(bar)
