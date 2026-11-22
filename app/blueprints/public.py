"""Customer-facing pages served on THIS platform's own domain:

  * GET /checkout/<id>  — branded redirect to the D-Money gateway checkout URL.
  * GET /payment/return — the redirect_url target shown after paying.

Both are public (the shopper is not logged into our dashboard).
"""
from flask import Blueprint, abort, redirect, render_template, request, url_for

from ..models import Payment

public_bp = Blueprint("public", __name__)


@public_bp.get("/checkout/<public_id>")
def checkout(public_id):
    """Own-domain checkout link: forward the shopper to the real gateway URL.

    Partners redirect customers to https://<platform>/checkout/<id> instead of the
    raw gateway URL — cleaner, branded, and we stay in control of the hop. A
    payment that's already settled skips the gateway and goes to its result page.
    """
    pay = Payment.query.filter_by(public_id=public_id).first()
    if not pay:
        abort(404)
    if pay.status != "PENDING":
        return redirect(url_for("public.payment_return", payment_id=pay.public_id))
    if not pay.checkout_url:
        abort(404)
    return redirect(pay.checkout_url)


@public_bp.get("/payment/return")
def payment_return():
    pid = (request.args.get("payment_id") or "").strip()
    order = (request.args.get("merch_order_id")
             or request.args.get("out_trade_no") or "").strip()

    pay = None
    if pid:
        pay = Payment.query.filter_by(public_id=pid).first()
    if not pay and order:
        pay = Payment.query.filter_by(merch_order_id=order).first()

    return render_template("payment_return.html", pay=pay)
