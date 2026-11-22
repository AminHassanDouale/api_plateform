"""Application factory — wires config, database, blueprints and template helpers."""
import os
import threading
import time

from flask import Flask

from .config import Config
from .models import db


def _start_reconcile_scheduler(app):
    """Opt-in in-process reconciler (RECONCILE_INTERVAL seconds). Off by default."""
    interval = app.config.get("RECONCILE_INTERVAL", 0) or 0
    if interval <= 0:
        return
    # Avoid starting twice under the Werkzeug reloader (only the child runs it).
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    def loop():
        from .reconcile import reconcile_pending
        while True:
            time.sleep(interval)
            with app.app_context():
                try:
                    result = reconcile_pending()
                    if result["updated"]:
                        app.logger.info("reconcile: updated %s payment(s)", result["updated"])
                except Exception as exc:
                    app.logger.warning("reconcile error: %s", exc)

    threading.Thread(target=loop, daemon=True).start()
    app.logger.info("reconcile scheduler started (every %ss)", interval)


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    db.init_app(app)

    # Blueprints
    from .blueprints.api import api_bp
    from .blueprints.webhook import webhook_bp
    from .blueprints.auth import auth_bp
    from .blueprints.dashboard import dashboard_bp
    from .blueprints.admin import admin_bp
    for bp in (api_bp, webhook_bp, auth_bp, dashboard_bp, admin_bp):
        app.register_blueprint(bp)

    # Make current_user available in every template.
    from .security import current_user

    @app.context_processor
    def inject_user():
        return {"current_user": current_user()}

    # Status badge colour helper for templates.
    @app.template_filter("badge")
    def badge(status):
        return {
            "SUCCESS": "ok", "PENDING": "warn",
            "FAILED": "bad", "CLOSED": "muted",
        }.get(status, "muted")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    # CLI: `flask --app run reconcile`
    @app.cli.command("reconcile")
    def reconcile_cmd():
        """Promote stale PENDING payments via D-Money QueryOrder."""
        from .reconcile import reconcile_pending
        result = reconcile_pending()
        print(f"reconcile: checked {result['checked']}, updated {result['updated']}")

    with app.app_context():
        db.create_all()

    _start_reconcile_scheduler(app)

    return app
