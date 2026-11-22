"""QueryOrder reconciliation.

Pulls the real status from D-Money for payments still PENDING after a grace
period (a webhook may have been missed, delayed, or our receiver was down).
Only promotes PENDING -> terminal; never overrides an already-settled payment.

Run it three ways:
  * on a schedule out-of-process :  python reconcile_job.py
  * via the Flask CLI            :  flask --app run reconcile
  * in-process (opt-in)          :  set RECONCILE_INTERVAL=60 before `python run.py`
"""
from datetime import datetime, timedelta

from flask import current_app

from .dmoney import DMoneyClient, DMoneyError
from .models import Payment, db

TERMINAL = {"SUCCESS", "FAILED", "CLOSED"}


def reconcile_pending(max_age_minutes=None, limit=200):
    if max_age_minutes is None:
        max_age_minutes = current_app.config.get("RECONCILE_MAX_AGE_MINUTES", 5)
    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)

    pending = (Payment.query
               .filter(Payment.status == "PENDING", Payment.created_at <= cutoff)
               .order_by(Payment.created_at.asc())
               .limit(limit).all())

    client = DMoneyClient(current_app.config)
    updated = 0
    for pay in pending:
        try:
            result = client.query_order(pay.merch_order_id)
        except DMoneyError:
            continue
        status = (result.get("trade_status") or "").upper()
        if status in TERMINAL:
            pay.status = status
            pay.trade_no = result.get("trade_no") or pay.trade_no
            if status == "SUCCESS" and not pay.paid_at:
                pay.paid_at = datetime.utcnow()
            updated += 1
    if updated:
        db.session.commit()
    return {"checked": len(pending), "updated": updated}
