"""Human login / logout for the dashboard & admin."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..models import User
from ..security import current_user, login_user, logout_user, verify_password

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard.home"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=email).first()
        if user and verify_password(user.password_hash, password):
            login_user(user)
            nxt = request.args.get("next") or url_for("dashboard.home")
            return redirect(nxt)
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@auth_bp.get("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
