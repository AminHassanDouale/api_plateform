"""Central configuration, all overridable via environment variables.

Defaults use the D-Money TEST credentials from PG.py so the platform runs out of
the box. For production, set every DMONEY_* and SECRET_KEY via the environment.
"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


class Config:
    # --- Flask ---
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "platform.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_SORT_KEYS = False

    # --- D-Money gateway (TEST defaults from PG.py) ---
    DMONEY_APPID = os.getenv("DMONEY_APPID", "1610279878784000")
    DMONEY_MERCH_CODE = os.getenv("DMONEY_MERCH_CODE", "200013")
    DMONEY_API_BASE_URL = os.getenv("DMONEY_API_BASE_URL", "https://pgtest.d-money.dj:38443")
    DMONEY_CHECKOUT_BASE_URL = os.getenv(
        "DMONEY_CHECKOUT_BASE_URL", "https://pgtest.d-money.dj:38443/payment/web/paygate"
    )
    DMONEY_APP_KEY = os.getenv("DMONEY_APP_KEY", "452fe2b7-4105-4fc8-b002-937d10a970b1")
    DMONEY_APP_SECRET = os.getenv("DMONEY_APP_SECRET", "d5d750fdcf550a6ae2f4fd15acd1357a")
    DMONEY_VERIFY_TLS = _env_bool("DMONEY_VERIFY_TLS", False)

    # Public host this platform is served on. The partner API, dashboard and the
    # D-Money notify webhook all live here. Override with PLATFORM_BASE_URL in dev.
    PLATFORM_BASE_URL = os.getenv("PLATFORM_BASE_URL", "https://pay.sahansolution.com")

    # notify_url points back at THIS platform's webhook (must be public HTTPS, this
    # is what we hand to D-Money). redirect_url is where the shopper lands after
    # paying (can be overridden per-payment by the partner via `return_url`).
    DMONEY_NOTIFY_URL = os.getenv(
        "DMONEY_NOTIFY_URL",
        "https://pay.sahansolution.com/user/v1/payments/d-money/notify",
    )
    DMONEY_DEFAULT_REDIRECT_URL = os.getenv(
        "DMONEY_DEFAULT_REDIRECT_URL", "https://pay.sahansolution.com/payment/return"
    )

    # Merchant private key. Either inline (raw base64 PKCS#8 body) OR a file path.
    # Prefer the PATH in production: the key is ~2.4 KB, which overflows systemd's
    # EnvironmentFile 2048-byte line limit if kept inline in a .env.
    DMONEY_PRIVATE_KEY_B64 = os.getenv("DMONEY_PRIVATE_KEY_B64", "")
    DMONEY_PRIVATE_KEY_PATH = os.getenv("DMONEY_PRIVATE_KEY_PATH", "")

    # D-Money PUBLIC key (PEM) for verifying inbound webhook signatures.
    DMONEY_PUBLIC_KEY_PATH = os.getenv(
        "DMONEY_PUBLIC_KEY_PATH", os.path.join(BASE_DIR, "dmoney_public_key.pem")
    )
    DMONEY_SIGNATURE_HEADER = os.getenv("DMONEY_SIGNATURE_HEADER", "X-DMoney-Signature")
    DMONEY_STRICT_SIGNATURE = _env_bool("DMONEY_STRICT_SIGNATURE", False)

    # SIMULATE mode: skip the live token/preOrder network calls and fabricate a
    # prepay_id, while STILL building a real signed checkout URL. Lets the whole
    # platform run + demo locally with no gateway connectivity. Turn OFF for real.
    DMONEY_SIMULATE = _env_bool("DMONEY_SIMULATE", True)

    # --- Reconciliation ---
    # Only reconcile payments older than this many minutes (give the webhook a
    # chance to arrive first). RECONCILE_INTERVAL > 0 starts an in-process
    # scheduler thread; 0 (default) means run it out-of-process instead.
    RECONCILE_MAX_AGE_MINUTES = int(os.getenv("RECONCILE_MAX_AGE_MINUTES", "5"))
    RECONCILE_INTERVAL = int(os.getenv("RECONCILE_INTERVAL", "0"))
