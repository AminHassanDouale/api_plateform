"""Standalone reconciliation run — schedule this (Windows Task Scheduler / cron).

    python reconcile_job.py

Promotes any payment still PENDING past the grace period to its real D-Money
status via QueryOrder. Exits after one pass.
"""
from app import create_app
from app.reconcile import reconcile_pending

app = create_app()

if __name__ == "__main__":
    with app.app_context():
        result = reconcile_pending()
        print(f"reconcile: checked {result['checked']}, updated {result['updated']}")
