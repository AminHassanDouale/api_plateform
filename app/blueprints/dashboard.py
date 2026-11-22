"""Partner dashboard — follow payments. Session-authenticated, partner-scoped."""
import csv
import io
from datetime import datetime, timedelta

from flask import (Blueprint, Response, abort, current_app, flash, redirect,
                   render_template, request, session, url_for)

from ..dmoney import DMoneyClient, DMoneyError
from ..models import ApiKey, Payment, db
from ..security import current_user, generate_api_key, login_required

dashboard_bp = Blueprint("dashboard", __name__)


def _scoped_query(user):
    """Admins see everything; partners see only their own payments."""
    q = Payment.query
    if not user.is_admin:
        q = q.filter_by(partner_id=user.partner_id)
    return q


@dashboard_bp.get("/")
@login_required
def home():
    user = current_user()
    if user.is_admin:
        return redirect(url_for("admin.overview"))
    return redirect(url_for("dashboard.payments"))


@dashboard_bp.get("/dashboard")
@login_required
def payments():
    user = current_user()
    q = _scoped_query(user)

    status = request.args.get("status", "").upper()
    search = request.args.get("q", "").strip()
    if status in {"PENDING", "SUCCESS", "FAILED", "CLOSED"}:
        q = q.filter_by(status=status)
    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(Payment.reference.ilike(like),
                            Payment.public_id.ilike(like),
                            Payment.customer_ref.ilike(like)))

    rows = q.order_by(Payment.created_at.desc()).limit(500).all()

    # Headline stats (partner-scoped).
    base = _scoped_query(user)
    today = datetime.utcnow().date()
    month_start = today.replace(day=1)
    total = base.count()
    success = base.filter_by(status="SUCCESS").count()
    pending = base.filter_by(status="PENDING").count()
    paid_today = base.filter(Payment.status == "SUCCESS",
                             Payment.paid_at >= datetime(today.year, today.month, today.day)).count()
    paid_month = base.filter(Payment.status == "SUCCESS",
                             Payment.paid_at >= datetime(month_start.year, month_start.month, 1)).count()
    stats = {
        "total": total, "success": success, "pending": pending,
        "paid_today": paid_today, "paid_month": paid_month,
        "rate": round(100 * success / total) if total else 0,
    }
    return render_template("dashboard/payments.html", rows=rows, stats=stats,
                           status=status, search=search)


@dashboard_bp.get("/dashboard/payments/<public_id>")
@login_required
def payment_detail(public_id):
    user = current_user()
    pay = _scoped_query(user).filter_by(public_id=public_id).first()
    if not pay:
        abort(404)
    return render_template("dashboard/detail.html", pay=pay)


@dashboard_bp.post("/dashboard/payments/<public_id>/refresh")
@login_required
def refresh_payment(public_id):
    """Pull the latest status from D-Money via QueryOrder."""
    user = current_user()
    pay = _scoped_query(user).filter_by(public_id=public_id).first()
    if not pay:
        abort(404)
    # Only a still-PENDING payment can change; never override a terminal status.
    if pay.status == "PENDING":
        try:
            result = DMoneyClient(current_app.config).query_order(pay.merch_order_id)
            new_status = (result.get("trade_status") or pay.status).upper()
            if new_status in {"SUCCESS", "FAILED", "CLOSED"}:
                pay.status = new_status
                pay.trade_no = result.get("trade_no") or pay.trade_no
                if new_status == "SUCCESS" and not pay.paid_at:
                    pay.paid_at = datetime.utcnow()
                db.session.commit()
        except DMoneyError:
            pass
    return redirect(url_for("dashboard.payment_detail", public_id=public_id))


@dashboard_bp.get("/dashboard/developers")
@login_required
def developers():
    user = current_user()
    if user.is_admin:
        return redirect(url_for("admin.overview"))
    keys = (ApiKey.query.filter_by(partner_id=user.partner_id)
            .order_by(ApiKey.created_at.desc()).all())
    new_key = session.pop("new_api_key", None)   # one-time reveal after generate
    base = current_app.config["PLATFORM_BASE_URL"].rstrip("/")
    return render_template("dashboard/developers.html", keys=keys,
                           new_key=new_key, base_url=base,
                           webhook_url=user.partner.webhook_url)


@dashboard_bp.post("/dashboard/developers/keys")
@login_required
def generate_key():
    user = current_user()
    if user.is_admin:
        abort(403)
    full, prefix, key_hash = generate_api_key()
    db.session.add(ApiKey(partner_id=user.partner_id, prefix=prefix, key_hash=key_hash))
    db.session.commit()
    session["new_api_key"] = full
    flash("New API key generated — copy it now, it is shown only once.", "success")
    return redirect(url_for("dashboard.developers"))


@dashboard_bp.post("/dashboard/developers/keys/<int:key_id>/revoke")
@login_required
def revoke_own_key(key_id):
    user = current_user()
    key = db.session.get(ApiKey, key_id)
    if key and key.partner_id == user.partner_id and key.active:
        key.revoked_at = datetime.utcnow()
        db.session.commit()
        flash("API key revoked.", "success")
    return redirect(url_for("dashboard.developers"))


@dashboard_bp.get("/dashboard/export.csv")
@login_required
def export_csv():
    user = current_user()
    rows = _scoped_query(user).order_by(Payment.created_at.desc()).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["payment_id", "reference", "amount", "currency", "status",
                "trade_no", "created_at", "paid_at"])
    for p in rows:
        w.writerow([p.public_id, p.reference or "", p.amount, p.currency, p.status,
                    p.trade_no or "", p.created_at, p.paid_at or ""])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=payments.csv"})
