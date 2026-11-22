# D-Money Payment Platform (Flask)

A multi-tenant payment integrator with a partner dashboard. Partners call one API
to create a payment and get a ready-to-use D-Money checkout link — they never
hold our keys or sign anything. They log into the dashboard to follow payments.

## Run

```bash
pip install -r requirements.txt
python seed.py        # create tables + demo admin, partner, API key, sample payments
python run.py         # http://localhost:5000
```

**Logins** (from `seed.py`):
- Admin:   `admin@platform.local` / `admin123`
- Partner: `partner@acme.test` / `partner123`
- A demo API key is printed by `seed.py`.

## Partner API

```bash
# Create a payment -> returns a checkout_url
curl -X POST http://localhost:5000/api/v1/payments \
  -H "Authorization: Bearer <API_KEY>" -H "Content-Type: application/json" \
  -d '{"amount":"30.00","currency":"DJF","reference":"ORDER-123","title":"Top-up"}'

# Poll status
curl http://localhost:5000/api/v1/payments/<payment_id> -H "Authorization: Bearer <API_KEY>"

# List
curl "http://localhost:5000/api/v1/payments?status=SUCCESS" -H "Authorization: Bearer <API_KEY>"
```

The partner's entire integration = call `POST /payments`, then redirect the
customer to the returned `checkout_url`.

## Webhook

D-Money POSTs results to `/notify` (aliases `/user/v1/payments/d-money/notify`,
`/d-money/notify`). The receiver verifies `X-DMoney-Signature`, updates the
payment, is idempotent against retries, and forwards to the partner's own
`webhook_url` if set.

## Developers page (self-service)

Partners get a **Developers** tab in the dashboard: view/generate/revoke their own
API keys (full key shown once) and copy-paste cURL / PHP (Laravel) / JS snippets
pre-filled with the live base URL.

## Reconciliation (QueryOrder)

Promotes any payment still `PENDING` past a grace period to its real D-Money
status (covers missed/late webhooks). Run it any of three ways:

```bash
python reconcile_job.py              # one pass — schedule via Task Scheduler / cron
flask --app run reconcile            # same, via the Flask CLI
RECONCILE_INTERVAL=60 python run.py  # in-process scheduler thread, every 60s
```

`RECONCILE_MAX_AGE_MINUTES` (default 5) controls the grace period before a pending
payment is checked.

## Structure

```
app/
  config.py              env-driven config (D-Money test defaults)
  dmoney.py              signing + token + preOrder + queryOrder + webhook verify
  models.py              Partner, User, ApiKey, Payment, WebhookEvent
  security.py            API-key auth + session login + role decorators
  blueprints/
    api.py               POST/GET /api/v1/payments
    webhook.py           /notify receiver
    auth.py              login / logout
    dashboard.py         partner dashboard (list, detail, CSV, refresh)
    admin.py             onboard partners, issue/revoke API keys
  templates/  static/    Jinja UI + CSS
run.py   seed.py
```

## Going live (switch off the test defaults)

Set these env vars (see `app/config.py`):

- `SECRET_KEY` — random, secret
- `DMONEY_SIMULATE=0` — make real token/preOrder/queryOrder calls
- `DMONEY_PRIVATE_KEY_B64` — your real merchant private key
- `DMONEY_APPID`, `DMONEY_MERCH_CODE`, `DMONEY_APP_KEY`, `DMONEY_APP_SECRET`
- `DMONEY_NOTIFY_URL` — public HTTPS URL of this app's `/notify`
- `DMONEY_PUBLIC_KEY_PATH` + `DMONEY_STRICT_SIGNATURE=1` — once D-Money gives you their public key
- `DATABASE_URL` — Postgres/MySQL for production

> **SIMULATE mode** (default ON) skips the live gateway network calls but still
> builds a real signed checkout URL, so the whole platform runs and demos with
> zero connectivity. Turn it off for real transactions.
