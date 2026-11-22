"""Admin panel — onboard partners, issue API keys, oversee all tenants."""
from datetime import datetime

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   session, url_for)

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
