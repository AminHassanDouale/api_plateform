"""Admin panel — onboard partners, issue API keys, oversee all tenants."""
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, session, url_for)

from ..dmoney import DMoneyClient, DMoneyError
from ..models import ApiKey, Partner, Payment, User, db
from ..security import (admin_required, generate_api_key, hash_password)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.get("/")
@admin_required
def overview():
    stats = {
        "partners": Partner.query.count(),
        "payments": Payment.query.count(),
        "pending": Payment.query.filter_by(status="PENDING").count(),
        "success": Payment.query.filter_by(status="SUCCESS").count(),
    }
    partners = Partner.query.order_by(Partner.created_at.desc()).all()
    return render_template("admin/overview.html", stats=stats, partners=partners)


@admin_bp.route("/partners/new", methods=["GET", "POST"])
@admin_required
def new_partner():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        login_email = (request.form.get("login_email") or email).strip().lower()
        password = request.form.get("password") or ""
        webhook_url = (request.form.get("webhook_url") or "").strip() or None

        if not name or not login_email or not password:
            flash("Name, login email and password are required.", "error")
            return render_template("admin/new_partner.html")
        if User.query.filter_by(email=login_email).first():
            flash("A user with that login email already exists.", "error")
            return render_template("admin/new_partner.html")

        partner = Partner(name=name, email=email, webhook_url=webhook_url)
        db.session.add(partner)
        db.session.flush()

        db.session.add(User(partner_id=partner.id, email=login_email,
                            password_hash=hash_password(password), role="partner"))

        full, prefix, key_hash = generate_api_key()
        db.session.add(ApiKey(partner_id=partner.id, prefix=prefix, key_hash=key_hash))
        db.session.commit()

        # Show the raw key exactly once.
        session["new_api_key"] = full
        flash("Partner created. Copy the API key now — it is shown only once.", "success")
        return redirect(url_for("admin.partner_detail", partner_id=partner.id))
    return render_template("admin/new_partner.html")


@admin_bp.get("/partners/<int:partner_id>")
@admin_required
def partner_detail(partner_id):
    partner = db.session.get(Partner, partner_id)
    if not partner:
        return "Not found", 404
    payments = (Payment.query.filter_by(partner_id=partner_id)
                .order_by(Payment.created_at.desc()).limit(50).all())
    new_key = session.pop("new_api_key", None)   # one-time reveal
    return render_template("admin/partner_detail.html", partner=partner,
                           payments=payments, new_key=new_key)


@admin_bp.post("/partners/<int:partner_id>/keys")
@admin_required
def issue_key(partner_id):
    partner = db.session.get(Partner, partner_id)
    if not partner:
        return "Not found", 404
    full, prefix, key_hash = generate_api_key()
    db.session.add(ApiKey(partner_id=partner_id, prefix=prefix, key_hash=key_hash))
    db.session.commit()
    session["new_api_key"] = full
    flash("New API key issued — copy it now.", "success")
    return redirect(url_for("admin.partner_detail", partner_id=partner_id))


@admin_bp.post("/keys/<int:key_id>/revoke")
@admin_required
def revoke_key(key_id):
    key = db.session.get(ApiKey, key_id)
    if not key:
        abort(404)
    if key.active:
        key.revoked_at = datetime.utcnow()
        db.session.commit()
        flash("API key revoked.", "success")
    return redirect(url_for("admin.partner_detail", partner_id=key.partner_id))


@admin_bp.post("/partners/<int:partner_id>/toggle")
@admin_required
def toggle_partner(partner_id):
    partner = db.session.get(Partner, partner_id)
    if partner:
        partner.status = "suspended" if partner.status == "active" else "active"
        db.session.commit()
    return redirect(url_for("admin.partner_detail", partner_id=partner_id))


# ---------------------------------------------------------------------------
# Internal payment sandbox — create test payments + simulate outcomes, in-browser
# ---------------------------------------------------------------------------
def _test_partner() -> Partner:
    """Get (or lazily create) the dedicated 'Test Shop' partner for sandbox use."""
    partner = Partner.query.filter_by(name="Test Shop").first()
    if not partner:
        partner = Partner(name="Test Shop", email="test@shop.local", status="active")
        db.session.add(partner)
        db.session.commit()
    return partner


@admin_bp.get("/sandbox")
@admin_required
def sandbox():
    partner = _test_partner()
    payments = (Payment.query.filter_by(partner_id=partner.id)
                .order_by(Payment.created_at.desc()).limit(25).all())
    return render_template(
        "admin/sandbox.html",
        payments=payments,
        base_url=current_app.config["PLATFORM_BASE_URL"].rstrip("/"),
        suggested_ref="TEST-" + secrets.token_hex(3).upper(),
        simulate=current_app.config["DMONEY_SIMULATE"],
    )


@admin_bp.post("/sandbox/create")
@admin_required
def sandbox_create():
    partner = _test_partner()
    base = current_app.config["PLATFORM_BASE_URL"].rstrip("/")

    amount_raw = (request.form.get("amount") or "250.00").strip()
    try:
        amount = Decimal(amount_raw)
        if not amount.is_finite() or amount <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        flash("Amount must be a positive number, e.g. 250.00.", "error")
        return redirect(url_for("admin.sandbox"))
    amount_str = f"{amount:.2f}"

    currency = (request.form.get("currency") or "DJF").upper()
    reference = (request.form.get("reference") or "").strip() or ("TEST-" + secrets.token_hex(3).upper())
    title = (request.form.get("title") or "Test checkout").strip()[:160]

    client = DMoneyClient(current_app.config)
    merch_order_id = client.new_order_id()
    try:
        prepay_id, checkout_url = client.create_checkout(
            merch_order_id, amount_str, title, currency,
            redirect_url=base + "/payment/return")
    except DMoneyError as exc:
        flash(f"Gateway error: {exc}", "error")
        return redirect(url_for("admin.sandbox"))

    pay = Payment(partner_id=partner.id, reference=reference, title=title,
                  amount=amount_str, currency=currency, merch_order_id=merch_order_id,
                  prepay_id=prepay_id, status="PENDING", checkout_url=checkout_url,
                  return_url=base + "/payment/return")
    db.session.add(pay)
    db.session.commit()
    flash(f"Created test payment {pay.public_id} — {amount_str} {currency}.", "success")
    return redirect(url_for("admin.sandbox"))


@admin_bp.post("/sandbox/<public_id>/simulate")
@admin_required
def sandbox_simulate(public_id):
    """Simulate D-Money confirming (or rejecting) a still-PENDING test payment."""
    pay = Payment.query.filter_by(public_id=public_id).first()
    if not pay:
        abort(404)
    outcome = (request.form.get("outcome") or "SUCCESS").upper()
    if pay.status == "PENDING" and outcome in {"SUCCESS", "FAILED", "CLOSED"}:
        pay.status = outcome
        pay.trade_no = pay.trade_no or ("DM-TEST-" + pay.merch_order_id[-8:])
        if outcome == "SUCCESS":
            pay.paid_at = datetime.utcnow()
        db.session.commit()
        flash(f"Simulated {outcome} for {public_id}.", "success")
    return redirect(url_for("admin.sandbox"))
