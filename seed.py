"""Seed the database with an admin, a demo partner, an API key and sample payments.

    python seed.py        # create/refresh demo data, print the demo API key

Safe to re-run: it resets the demo partner so you always get a fresh API key.
"""
from datetime import datetime, timedelta

from app import create_app
from app.dmoney import DMoneyClient
from app.models import ApiKey, Partner, Payment, User, db
from app.security import generate_api_key, hash_password

app = create_app()

with app.app_context():
    # --- admin ---
    admin = User.query.filter_by(email="admin@platform.local").first()
    if not admin:
        db.session.add(User(email="admin@platform.local",
                            password_hash=hash_password("admin123"), role="admin"))

    # --- demo partner (reset each run) ---
    old = Partner.query.filter_by(name="Acme Store").first()
    if old:
        db.session.delete(old)
        db.session.commit()

    partner = Partner(name="Acme Store", email="ops@acme.test",
                      webhook_url=None, status="active")
    db.session.add(partner)
    db.session.flush()

    db.session.add(User(partner_id=partner.id, email="partner@acme.test",
                        password_hash=hash_password("partner123"), role="partner"))

    full_key, prefix, key_hash = generate_api_key()
    db.session.add(ApiKey(partner_id=partner.id, prefix=prefix, key_hash=key_hash))

    # --- sample payments ---
    client = DMoneyClient(app.config)
    samples = [
        ("ORDER-1001", "Wallet top-up", "30.00", "SUCCESS"),
        ("ORDER-1002", "Premium plan", "120.00", "SUCCESS"),
        ("ORDER-1003", "Wallet top-up", "15.00", "PENDING"),
        ("ORDER-1004", "Gift card", "50.00", "FAILED"),
        ("ORDER-1005", "Wallet top-up", "75.00", "SUCCESS"),
    ]
    for i, (ref, title, amount, status) in enumerate(samples):
        moid = client.new_order_id()
        prepay_id, checkout_url = client.create_checkout(moid, amount, title, "DJF")
        pay = Payment(
            partner_id=partner.id, reference=ref, title=title, amount=amount,
            currency="DJF", customer_ref=f"user-{100 + i}", merch_order_id=moid,
            prepay_id=prepay_id, status=status, checkout_url=checkout_url,
            created_at=datetime.utcnow() - timedelta(hours=i * 7),
            paid_at=(datetime.utcnow() - timedelta(hours=i * 7)) if status == "SUCCESS" else None,
            trade_no=("DM" + moid[-10:]) if status == "SUCCESS" else None,
        )
        db.session.add(pay)

    db.session.commit()

    print("=" * 64)
    print("  SEED COMPLETE")
    print("=" * 64)
    print("  Admin login    : admin@platform.local / admin123")
    print("  Partner login  : partner@acme.test / partner123")
    print("  Demo API key   :", full_key)
    print("=" * 64)
    print("  Start:  python run.py   ->  http://localhost:5000")
    print("=" * 64)
