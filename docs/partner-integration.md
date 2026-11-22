# Payment Platform — Partner Integration Guide

Accept D-Money payments with a **single API call**. You create a payment, we hand
you a ready-to-use checkout link, the customer pays, and we tell you the result.

You never hold D-Money keys, never sign anything, and never talk to the gateway
directly — the platform does all of that for you.

---

## 1. The big picture

```
 Your backend                Platform                 D-Money              Customer
      │                         │                        │                    │
      │  POST /api/v1/payments  │                        │                    │
      │────────────────────────▶│  create + sign order   │                    │
      │                         │───────────────────────▶│                    │
      │  { checkout_url, ... }  │                        │                    │
      │◀────────────────────────│                        │                    │
      │                                                                       │
      │   redirect customer to checkout_url ──────────────────────────────▶ pays
      │                                                                       │
      │                         │   notify (result)      │                    │
      │                         │◀───────────────────────│                    │
      │   webhook to YOUR url   │                        │                    │
      │◀────────────────────────│   (or you poll GET)    │                    │
```

Your entire integration is **two steps**:

1. `POST /api/v1/payments` → get a `checkout_url`.
2. Redirect the customer to that `checkout_url`.

Then learn the result either by **webhook** (we call you) or by **polling**
`GET /api/v1/payments/{id}`.

---

## 2. Base URL & credentials

| | |
|---|---|
| **Base URL** | `https://pay.sahansolution.com` *(see the exact live URL on your dashboard's **Developers** tab)* |
| **API version** | `/api/v1` |
| **Auth** | API key, sent on every request |

Your API key looks like `prt_live_xxxxxxxxxxxxxxxxxxxx`. Generate, view (once),
and revoke keys yourself under **Dashboard → Developers**.

> ⚠️ **Keep your key server-side only.** It authenticates as your whole account.
> Never ship it in a browser, mobile app, or public repo. If it leaks, revoke it
> from the Developers tab and generate a new one.

### Authentication header

Send your key one of two ways (Bearer is preferred):

```
Authorization: Bearer prt_live_xxxxxxxxxxxxxxxxxxxx
```
or
```
X-API-Key: prt_live_xxxxxxxxxxxxxxxxxxxx
```

---

## 3. Create a payment

`POST /api/v1/payments`

### Request body (JSON)

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `amount` | **yes** | string | Positive decimal, e.g. `"30.00"`. Sent as a string to avoid float rounding. |
| `currency` | no | string | One of `DJF`, `USD`, `EUR`. Default `DJF`. |
| `reference` | recommended | string | **Your** order ID. Used as the idempotency key (see §6). |
| `title` | no | string | Shown on the checkout page. Default `"Payment"`. Max 160 chars. |
| `customer_ref` | no | string | Your own customer identifier. Stored, returned to you, never shown to the payer. |
| `return_url` | no | string | Where the customer lands after paying. Falls back to the platform default. |

### Example

```bash
curl -X POST https://pay.sahansolution.com/api/v1/payments \
  -H "Authorization: Bearer prt_live_xxxxxxxxxxxxxxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{
        "amount": "30.00",
        "currency": "DJF",
        "reference": "ORDER-123",
        "title": "Wallet top-up",
        "customer_ref": "user-42",
        "return_url": "https://your-site.com/thank-you"
      }'
```

### Response — `201 Created`

```json
{
  "payment_id": "pay_328b97aff888290e4ec6",
  "reference": "ORDER-123",
  "amount": "30.00",
  "currency": "DJF",
  "status": "PENDING",
  "trade_no": null,
  "checkout_url": "https://pgtest.d-money.dj:38443/payment/web/paygate?appid=...&sign=...",
  "created_at": "2026-11-22T07:31:08.885010Z",
  "paid_at": null,
  "expires_at": "2026-11-22T09:31:08.892666Z"
}
```

**Next step:** redirect the customer's browser to `checkout_url`. The link is
valid until `expires_at` (120 minutes after creation).

---

## 4. Get / poll a payment

`GET /api/v1/payments/{payment_id}`

```bash
curl https://pay.sahansolution.com/api/v1/payments/pay_328b97aff888290e4ec6 \
  -H "Authorization: Bearer prt_live_xxxxxxxxxxxxxxxxxxxx"
```

### Response — `200 OK`

```json
{
  "payment_id": "pay_328b97aff888290e4ec6",
  "reference": "ORDER-123",
  "amount": "30.00",
  "currency": "DJF",
  "status": "SUCCESS",
  "trade_no": "DM6400466178",
  "checkout_url": "https://pgtest.d-money.dj:38443/payment/web/paygate?...",
  "created_at": "2026-11-22T07:31:08.885010Z",
  "paid_at": "2026-11-22T07:33:41.000000Z"
}
```

Unknown ID → `404 { "error": "not_found" }`. You can only fetch payments that
belong to your own account.

---

## 5. List payments

`GET /api/v1/payments`

| Query param | Default | Notes |
|-------------|---------|-------|
| `status` | — | Filter by `PENDING` / `SUCCESS` / `FAILED` / `CLOSED`. |
| `page` | `1` | Page number. |
| `per_page` | `20` | Max `100`. |

```bash
curl "https://pay.sahansolution.com/api/v1/payments?status=SUCCESS&page=1&per_page=20" \
  -H "Authorization: Bearer prt_live_xxxxxxxxxxxxxxxxxxxx"
```

### Response — `200 OK`

```json
{
  "page": 1,
  "per_page": 20,
  "total": 6,
  "data": [ { "payment_id": "pay_...", "status": "SUCCESS", "...": "..." } ]
}
```

---

## 6. Idempotency (safe retries)

Pass a unique `reference` (your order ID) on every create. If you send the **same
`reference` twice**, we return the **original** payment instead of creating a
duplicate — the response is `200 OK` and includes `"idempotent": true`:

```json
{
  "payment_id": "pay_328b97aff888290e4ec6",
  "reference": "ORDER-123",
  "status": "PENDING",
  "idempotent": true,
  "...": "..."
}
```

This makes it safe to retry a create after a network timeout without
double-charging a customer. **Always send a `reference`.**

---

## 7. Payment statuses

| Status | Meaning |
|--------|---------|
| `PENDING` | Created; customer has not completed payment yet. |
| `SUCCESS` | Paid. `paid_at` and `trade_no` are set. |
| `FAILED` | Payment attempt failed. |
| `CLOSED` | Expired or cancelled before completion. |

Status only ever moves **from `PENDING` to a final state**. A settled payment is
never silently changed.

---

## 8. Webhooks — getting the result pushed to you

If you give us a `webhook_url`, we POST the final payment result to it as soon as
D-Money confirms it — so you don't have to poll.

> Your `webhook_url` is configured by your account manager during onboarding.
> It's shown (read-only) on your **Developers** tab.

### What we send

A POST with a JSON body identical to the payment object:

```http
POST https://your-site.com/webhooks/payments
Content-Type: application/json

{
  "payment_id": "pay_328b97aff888290e4ec6",
  "reference": "ORDER-123",
  "amount": "30.00",
  "currency": "DJF",
  "status": "SUCCESS",
  "trade_no": "DM6400466178",
  "created_at": "2026-11-22T07:31:08.885010Z",
  "paid_at": "2026-11-22T07:33:41.000000Z"
}
```

### How to handle it

1. Respond **`200`** quickly. (We time out after 5 seconds; non-200 is just logged.)
2. **Match on `reference`** (your order ID) or `payment_id`.
3. **Treat it as idempotent** — design your handler so re-delivery of the same
   result is a no-op. Only act on a transition *into* `SUCCESS`.
4. **Confirm before fulfilling.** As defence-in-depth, call
   `GET /api/v1/payments/{payment_id}` and verify `status == "SUCCESS"` and the
   `amount`/`currency` match your order before releasing goods.

> **Belt and braces:** webhook delivery is best-effort. Also poll
> `GET /api/v1/payments/{id}` (e.g. when the customer returns to your
> `return_url`) so a missed webhook never leaves an order stuck.

---

## 9. Errors

All errors return a JSON body of the shape:

```json
{ "error": "invalid_amount", "message": "Human-readable explanation." }
```

| HTTP | `error` | When |
|------|---------|------|
| `400` | `invalid_amount` | `amount` missing, non-numeric, or ≤ 0. |
| `400` | `invalid_currency` | `currency` not in `DJF` / `USD` / `EUR`. |
| `401` | `missing_api_key` | No `Authorization` / `X-API-Key` header. |
| `401` | `invalid_api_key` | Key is wrong or revoked. |
| `403` | `partner_suspended` | Your account is suspended — contact support. |
| `404` | `not_found` | No such payment under your account. |
| `502` | `gateway_error` | D-Money rejected or was unreachable. Safe to retry. |

---

## 10. End-to-end examples

### PHP (Laravel / Guzzle)

```php
$res = Http::withToken(env('DMONEY_PLATFORM_KEY'))
    ->post('https://pay.sahansolution.com/api/v1/payments', [
        'amount'     => '30.00',
        'currency'   => 'DJF',
        'reference'  => $order->id,          // your order id = idempotency key
        'title'      => 'Wallet top-up',
        'return_url' => route('payment.return'),
    ]);

abort_unless($res->successful(), 502, 'Payment init failed');

return redirect()->away($res['checkout_url']);   // send the customer to pay
```

### Node.js (fetch)

```js
const r = await fetch("https://pay.sahansolution.com/api/v1/payments", {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${process.env.DMONEY_PLATFORM_KEY}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    amount: "30.00",
    currency: "DJF",
    reference: order.id,
    title: "Wallet top-up",
    return_url: "https://your-site.com/thank-you",
  }),
});

if (!r.ok) throw new Error(`payment init failed: ${r.status}`);
const { checkout_url } = await r.json();
res.redirect(checkout_url);                        // send the customer to pay
```

### Python (requests)

```python
import os, requests

r = requests.post(
    "https://pay.sahansolution.com/api/v1/payments",
    headers={"Authorization": f"Bearer {os.environ['DMONEY_PLATFORM_KEY']}"},
    json={
        "amount": "30.00",
        "currency": "DJF",
        "reference": order_id,                     # idempotency key
        "title": "Wallet top-up",
        "return_url": "https://your-site.com/thank-you",
    },
    timeout=30,
)
r.raise_for_status()
checkout_url = r.json()["checkout_url"]             # redirect your customer here
```

### Poll the status later

```bash
curl https://pay.sahansolution.com/api/v1/payments/pay_xxx \
  -H "Authorization: Bearer prt_live_xxxxxxxxxxxxxxxxxxxx"
# → { "status": "SUCCESS", "trade_no": "DM...", "paid_at": "..." }
```

---

## 11. Integration checklist

- [ ] Store your API key in server-side config/secrets — never in client code.
- [ ] Send a unique `reference` (your order ID) on every create.
- [ ] Redirect the customer to `checkout_url`; handle your `return_url` landing.
- [ ] Expose a `webhook_url` (ask your account manager to register it) **and**
      poll `GET /payments/{id}` as a fallback.
- [ ] On `SUCCESS`, verify `amount` + `currency` match the order before fulfilling.
- [ ] Make your webhook handler idempotent (safe to receive the same result twice).
- [ ] Handle `502 gateway_error` with a retry; handle `4xx` by fixing the request.

---

## 12. Quick reference

| Action | Method & path |
|--------|---------------|
| Create payment | `POST /api/v1/payments` |
| Get / poll payment | `GET /api/v1/payments/{payment_id}` |
| List payments | `GET /api/v1/payments?status=&page=&per_page=` |
| Auth header | `Authorization: Bearer <key>` *(or `X-API-Key: <key>`)* |

*Need help? Contact your account manager or the platform support team.*
