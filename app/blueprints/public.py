"""Customer-facing post-payment landing page — the `redirect_url` target.

D-Money redirects the shopper here after they finish (or abandon) paying. We look
the payment up by our own `payment_id` or by D-Money's `merch_order_id` (whichever
is present in the query string) and show its current status. The authoritative
status still arrives via the /notify webhook; this page just reflects what we know.
"""
from flask import Blueprint, render_template, request

from ..models import Payment

public_bp = Blueprint("public", __name__)


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
