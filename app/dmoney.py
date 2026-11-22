"""D-Money gateway client — signing, token, preOrder, queryOrder, webhook verify.

The signing rules are lifted verbatim from the proven PG.py:
  * request sign : flatten biz_content -> drop meta/empty -> sort k=v -> join '&'
                   -> RSA-PSS / SHA-256 -> base64
  * checkout URL : sign ONLY 5 fields, append the signature RAW (not url-encoded)
This module is configured from flask app.config and is otherwise framework-free.
"""
import base64
import os
import random
import string
import textwrap
import time

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# Default TEST private key (raw base64 PKCS#8), identical to PG.py, so the
# platform signs correctly out of the box. Override with DMONEY_PRIVATE_KEY_B64.
DEFAULT_PRIVATE_KEY_B64 = (
    "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"
    "O5cTUZH0MyMYcHmfZDSO2LU/x+DeuO31YCs="
)

EXCLUDED_FROM_SIGN = {
    "sign", "sign_type", "header", "biz_content",
    "refund_info", "openType", "raw_request",
}


class DMoneyError(RuntimeError):
    """Raised when the gateway rejects a request or returns an error."""


class DMoneyClient:
    """Stateful client bound to one set of merchant credentials."""

    def __init__(self, cfg):
        self.appid = cfg["DMONEY_APPID"]
        self.merch_code = cfg["DMONEY_MERCH_CODE"]
        self.api_base = cfg["DMONEY_API_BASE_URL"].rstrip("/")
        self.checkout_base = cfg["DMONEY_CHECKOUT_BASE_URL"]
        self.app_key = cfg["DMONEY_APP_KEY"]
        self.app_secret = cfg["DMONEY_APP_SECRET"]
        self.verify_tls = cfg["DMONEY_VERIFY_TLS"]
        self.notify_url = cfg["DMONEY_NOTIFY_URL"]
        self.default_redirect = cfg["DMONEY_DEFAULT_REDIRECT_URL"]
        self.simulate = cfg["DMONEY_SIMULATE"]
        self.sig_header = cfg["DMONEY_SIGNATURE_HEADER"]

        b64 = (cfg.get("DMONEY_PRIVATE_KEY_B64") or "").strip()
        key_path = (cfg.get("DMONEY_PRIVATE_KEY_PATH") or "").strip()
        if not b64 and key_path and os.path.exists(key_path):
            self.private_key = self._load_private_key_file(key_path)
        else:
            self.private_key = self._load_private_key(b64 or DEFAULT_PRIVATE_KEY_B64)
        self.public_key = self._load_public_key(cfg.get("DMONEY_PUBLIC_KEY_PATH"))

        self._token = None
        self._token_exp = 0

    # ----- key loading -----
    @staticmethod
    def _load_private_key(b64_body: str):
        body = "\n".join(textwrap.wrap(b64_body.strip(), 64))
        pem = f"-----BEGIN PRIVATE KEY-----\n{body}\n-----END PRIVATE KEY-----\n"
        return serialization.load_pem_private_key(pem.encode(), password=None)

    @staticmethod
    def _load_private_key_file(path: str):
        """Load the merchant key from a file — either a full PEM or a raw base64 body."""
        with open(path, "rb") as fh:
            data = fh.read().strip()
        if b"-----BEGIN" in data:
            return serialization.load_pem_private_key(data, password=None)
        return DMoneyClient._load_private_key(data.decode())

    @staticmethod
    def _load_public_key(path):
        if not path or not os.path.exists(path):
            return None
        with open(path, "rb") as fh:
            return serialization.load_pem_public_key(fh.read())

    # ----- primitives -----
    @staticmethod
    def nonce(length: int = 32) -> str:
        return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))

    @staticmethod
    def new_order_id() -> str:
        return f"{int(time.time() * 1000)}{random.randint(1000, 9999)}"

    def _raw_string(self, params: dict) -> str:
        flat = {}
        for k, v in params.items():
            if k == "biz_content" and isinstance(v, dict):
                flat.update(v)
            elif k not in EXCLUDED_FROM_SIGN:
                flat[k] = v
        filtered = {
            k: str(v) for k, v in flat.items()
            if k not in EXCLUDED_FROM_SIGN and v is not None and str(v).strip() != ""
        }
        return "&".join(f"{k}={v}" for k, v in sorted(filtered.items()))

    def _sign(self, raw: str) -> str:
        sig = self.private_key.sign(
            raw.encode("utf-8"),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return base64.b64encode(sig).decode()

    # ----- Step 1: token -----
    def get_token(self) -> str:
        if self._token and time.time() < self._token_exp:
            return self._token
        headers = {"X-APP-Key": self.app_key, "Content-Type": "application/json"}
        body = {"appSecret": self.app_secret}
        errors = []
        for path in ("/apiaccess/payment/gateway/payment/v1/token",
                     "/payment/gateway/payment/v1/token"):
            resp = requests.post(self.api_base + path, headers=headers, json=body,
                                 verify=self.verify_tls, timeout=30)
            try:
                data = resp.json()
            except ValueError:
                data = {}
            token = data.get("token")
            if token and not data.get("errorCode") and str(data.get("code", "0")) == "0":
                self._token = token
                self._token_exp = time.time() + 1800  # cache ~30 min
                return token
            errors.append(f"{path} -> HTTP {resp.status_code}: "
                          f"{data.get('errorMsg') or data.get('message') or resp.text[:160]}")
        raise DMoneyError("Token request failed: " + " | ".join(errors))

    # ----- Step 2: preOrder -----
    def preorder(self, merch_order_id, amount, title, currency, redirect_url=None,
                 callback_info=None):
        params = {
            "method": "payment.preorder",
            "version": "1.0",
            "nonce_str": self.nonce(),
            "timestamp": str(int(time.time())),
            "biz_content": {
                "appid": self.appid,
                "merch_code": self.merch_code,
                "merch_order_id": merch_order_id,
                "notify_url": self.notify_url,
                "redirect_url": redirect_url or self.default_redirect,
                "timeout_express": "120m",
                "trade_type": "Checkout",
                "title": title,
                "total_amount": amount,
                "trans_currency": currency,
                "business_type": "OnlineMerchant",
                "callback_info": callback_info or f"oid-{merch_order_id}",
            },
            "sign_type": "SHA256WithRSA",
        }
        params["sign"] = self._sign(self._raw_string(params))

        token = self.get_token()
        auth = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        headers = {"Content-Type": "application/json", "Authorization": auth,
                   "X-APP-Key": self.app_key}
        last = None
        for path in ("/apiaccess/payment/gateway/payment/v1/merchant/preOrder",
                     "/payment/gateway/payment/v1/merchant/preOrder"):
            resp = requests.post(self.api_base + path, headers=headers, json=params,
                                 verify=self.verify_tls, timeout=30)
            last = resp
            if resp.ok:
                data = resp.json()
                if str(data.get("code")) != "0":
                    raise DMoneyError(f"preOrder rejected: {data}")
                prepay_id = (data.get("biz_content") or {}).get("prepay_id")
                if not prepay_id:
                    raise DMoneyError(f"No prepay_id in response: {data}")
                return prepay_id
        raise DMoneyError(f"preOrder failed: {last.status_code if last else '?'} "
                          f"{last.text[:200] if last else ''}")

    # ----- Step 3: signed checkout URL -----
    def checkout_url(self, prepay_id, language="en"):
        params = {
            "appid": self.appid,
            "merch_code": self.merch_code,
            "nonce_str": self.nonce(),
            "prepay_id": prepay_id,
            "timestamp": str(int(time.time())),
        }
        signed_keys = ["appid", "merch_code", "nonce_str", "prepay_id", "timestamp"]
        raw = "&".join(f"{k}={params[k]}" for k in sorted(signed_keys))
        sign = self._sign(raw)
        ordered = [
            ("appid", params["appid"]), ("merch_code", params["merch_code"]),
            ("nonce_str", params["nonce_str"]), ("prepay_id", params["prepay_id"]),
            ("timestamp", params["timestamp"]), ("sign", sign),
            ("sign_type", "SHA256WithRSA"), ("version", "1.0"),
            ("trade_type", "Checkout"), ("language", language),
        ]
        query = "&".join(f"{k}={v}" for k, v in ordered)
        return f"{self.checkout_base}?{query}"

    # ----- high-level: create a full checkout -----
    def create_checkout(self, merch_order_id, amount, title, currency,
                        redirect_url=None):
        """Return (prepay_id, checkout_url). In SIMULATE mode, skip the network
        calls but still build a REAL signed checkout URL with a fake prepay_id."""
        if self.simulate:
            prepay_id = "SIMPP" + self.nonce(18).upper()
        else:
            prepay_id = self.preorder(merch_order_id, amount, title, currency,
                                      redirect_url)
        return prepay_id, self.checkout_url(prepay_id)

    # ----- Step 5: QueryOrder -----
    def query_order(self, merch_order_id):
        if self.simulate:
            return {"merch_order_id": merch_order_id, "trade_status": "PENDING"}
        params = {
            "method": "payment.queryorder",
            "version": "1.0",
            "nonce_str": self.nonce(),
            "timestamp": str(int(time.time())),
            "biz_content": {
                "appid": self.appid,
                "merch_code": self.merch_code,
                "merch_order_id": merch_order_id,
            },
            "sign_type": "SHA256WithRSA",
        }
        params["sign"] = self._sign(self._raw_string(params))
        token = self.get_token()
        auth = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        headers = {"Content-Type": "application/json", "Authorization": auth,
                   "X-APP-Key": self.app_key}
        for path in ("/apiaccess/payment/gateway/payment/v1/merchant/queryOrder",
                     "/payment/gateway/payment/v1/merchant/queryOrder"):
            resp = requests.post(self.api_base + path, headers=headers, json=params,
                                 verify=self.verify_tls, timeout=30)
            if resp.ok:
                data = resp.json()
                if str(data.get("code")) != "0":
                    raise DMoneyError(f"queryOrder rejected: {data}")
                return data.get("biz_content") or {}
        raise DMoneyError("queryOrder failed")

    # ----- webhook signature verification -----
    def verify_webhook(self, raw_body: bytes, signature_b64: str):
        """Return the scheme name that verified, or None. Tries PSS then PKCS1v15."""
        if not self.public_key or not signature_b64:
            return None
        try:
            signature = base64.b64decode(signature_b64)
        except Exception:
            return None
        for name, pad in (
            ("RSA-PSS", padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                                    salt_length=padding.PSS.DIGEST_LENGTH)),
            ("PKCS1v15", padding.PKCS1v15()),
        ):
            try:
                self.public_key.verify(signature, raw_body, pad, hashes.SHA256())
                return name
            except (InvalidSignature, Exception):
                continue
        return None
