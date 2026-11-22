# Deploying the D-Money platform to `pay.sahansolution.com`

Target: Ubuntu 24.04 at `187.124.32.203`, nginx + gunicorn + systemd + Let's Encrypt.
Run everything over SSH as `root` (or with `sudo`).

> **Prerequisite:** the DNS A record `pay → 187.124.32.203` must already exist and
> have propagated (check: `dig +short pay.sahansolution.com` returns the IP).
> Certbot in step 8 will fail until it resolves.

---

## 0 · System packages

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git nginx certbot python3-certbot-nginx
```

## 1 · Clone the repo

```bash
cd /var/www
sudo git clone https://github.com/AminHassanDouale/api_plateform.git pay.sahansolution.com
cd pay.sahansolution.com
```
*(If the clone asks for a username/password, the repo is private — create a GitHub
Personal Access Token or add a deploy key, then retry.)*

## 2 · Virtualenv + dependencies + gunicorn

```bash
sudo python3 -m venv .venv
sudo .venv/bin/pip install --upgrade pip
sudo .venv/bin/pip install -r requirements.txt gunicorn
```

## 3 · Production environment file

Start in **SIMULATE mode** (keeps the working D-Money TEST sandbox, no real money)
so you can prove the stack end-to-end before you have live merchant credentials.

```bash
sudo tee .env >/dev/null <<EOF
PLATFORM_BASE_URL=https://pay.sahansolution.com
DMONEY_NOTIFY_URL=https://pay.sahansolution.com/user/v1/payments/d-money/notify
SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_hex(32))')
DMONEY_SIMULATE=1
EOF
```

## 4 · Ownership (www-data runs the app and writes the SQLite DB)

```bash
sudo chown -R www-data:www-data /var/www/pay.sahansolution.com
```

## 5 · Create tables + one real admin user

Do **not** run `seed.py` in production (it creates a demo partner with weak
passwords). Create a real admin instead — pick a strong password:

```bash
sudo -u www-data .venv/bin/python - <<'PY'
from app import create_app
from app.models import db, User
from app.security import hash_password
app = create_app()
with app.app_context():
    db.create_all()
    email = "admin@sahansolution.com"
    if not User.query.filter_by(email=email).first():
        db.session.add(User(email=email,
                            password_hash=hash_password("REPLACE_WITH_STRONG_PASSWORD"),
                            role="admin"))
        db.session.commit(); print("admin created:", email)
    else:
        print("admin already exists:", email)
PY
```

## 6 · systemd service (gunicorn)

```bash
sudo cp deploy/gunicorn-dmoney.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gunicorn-dmoney
sudo systemctl status gunicorn-dmoney --no-pager
```

## 7 · nginx vhost

```bash
sudo cp deploy/nginx-pay.sahansolution.com.conf /etc/nginx/sites-available/pay.sahansolution.com
sudo ln -sf /etc/nginx/sites-available/pay.sahansolution.com /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 8 · TLS certificate (HTTPS) — required by D-Money

```bash
sudo certbot --nginx -d pay.sahansolution.com --redirect -m admin@sahansolution.com --agree-tos
```

## 9 · Verify

```bash
curl -I  http://pay.sahansolution.com/healthz     # should 301 -> https
curl -s  https://pay.sahansolution.com/healthz     # {"status":"ok"}
curl -s  https://pay.sahansolution.com/notify      # {"status":"ok","service":"d-money notify"}
```

Then open `https://pay.sahansolution.com/login` and sign in as the admin.

---

## Going fully live (when D-Money issues production credentials)

Edit `/var/www/pay.sahansolution.com/.env`, add the real values, flip the toggles:

```bash
DMONEY_SIMULATE=0
DMONEY_STRICT_SIGNATURE=1
DMONEY_VERIFY_TLS=1
DMONEY_PRIVATE_KEY_B64=<your real merchant private key>
DMONEY_APPID=<...>
DMONEY_MERCH_CODE=<...>
DMONEY_APP_KEY=<...>
DMONEY_APP_SECRET=<...>
DMONEY_PUBLIC_KEY_PATH=/var/www/pay.sahansolution.com/dmoney_public_key.pem
```

Then restart: `sudo systemctl restart gunicorn-dmoney`.

Give D-Money this notify URL: `https://pay.sahansolution.com/user/v1/payments/d-money/notify`

## Updating after a new push

```bash
cd /var/www/pay.sahansolution.com
sudo -u www-data git pull
sudo .venv/bin/pip install -r requirements.txt
sudo systemctl restart gunicorn-dmoney
```

## Reconciliation (optional, catches missed webhooks)

Add a cron entry to promote stale PENDING payments every 5 minutes:

```bash
echo '*/5 * * * * www-data cd /var/www/pay.sahansolution.com && .venv/bin/python reconcile_job.py >> /var/log/dmoney-reconcile.log 2>&1' | sudo tee /etc/cron.d/dmoney-reconcile
```

## Logs & troubleshooting

```bash
sudo journalctl -u gunicorn-dmoney -f          # app logs (live)
sudo tail -f /var/log/nginx/pay.sahansolution.com.error.log
```

> **Note on the database:** this starts on SQLite (`platform.db`), fine for low
> volume. For higher concurrency (many simultaneous webhooks + API calls), move to
> Postgres: `apt install postgresql`, create a DB/user, then set
> `DATABASE_URL=postgresql+psycopg://user:pass@localhost/dmoney` in `.env`
> (add `psycopg[binary]` to the venv) and restart.
