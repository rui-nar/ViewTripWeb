# Billing and tier plans

Issue #121. Two plans — **Free** and **Cloud** — with payments through Stripe.

**Self-hosting is not affected.** With no payment provider configured there is
no billing: the payment endpoints return 404, no paywall exists anywhere in the
client, and every account has unlimited trips and storage. The landing page's
"Self-hosted · MIT · Unlimited projects, users" is enforced by
`billing_enabled()` returning False, not by good intentions.

## What the plans limit

| | Free | Cloud |
|---|---|---|
| Trips | 1 | unlimited |
| Photo storage | 500 MB | 20 GB |

Both numbers are environment variables (`FREE_MAX_PROJECTS`,
`FREE_MAX_STORAGE_MB`, `CLOUD_MAX_PROJECTS`, `CLOUD_MAX_STORAGE_MB`), read per
request — retuning them is a container restart, not a release.

Nothing else is gated yet. Strava/Polarsteps sync, posters, sharing, companions
and encounters are on every plan.

Storage is attributed to the **trip owner**: a companion uploading photos to a
shared trip spends the owner's allowance, because that is whose directory the
files land in.

## Turning it on

Two switches, deliberately separate:

```
BILLING_ENABLED=1          # sell plans; measure usage; show the plan UI
BILLING_ENFORCE_QUOTAS=1   # start refusing writes past the limit (402)
```

Enable the first one alone at first. Usage counters fill in, `/api/billing/me`
reports real numbers, and nobody is blocked. Flip the second only once you have
looked at what existing accounts actually use — otherwise everyone who grew
past 500 MB before the limits existed is locked out the moment you deploy.

## Stripe setup

1. **Product and price** — create a recurring monthly price for the Cloud plan.
   Copy its `price_...` id into `STRIPE_PRICE_CLOUD_MONTHLY`.
2. **Webhook endpoint** — point it at `https://<host>/api/billing/webhook` and
   subscribe to:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_failed`

   Copy the signing secret (`whsec_...`) into `STRIPE_WEBHOOK_SECRET`.
3. **Customer portal** — enable it in the Stripe dashboard (Settings → Billing →
   Customer portal). "Manage billing" opens it; cancellations and card updates
   happen there and come back as webhooks.
4. **Secret key** → `STRIPE_SECRET_KEY`.

All four are **runtime** environment variables. Never pass them to
`docker build` — the published image is public.

### Local testing

```bash
export BILLING_ENABLED=1 BILLING_ENFORCE_QUOTAS=1
export STRIPE_SECRET_KEY=sk_test_... STRIPE_PRICE_CLOUD_MONTHLY=price_...
stripe listen --forward-to localhost:8000/api/billing/webhook
# copy the whsec_... it prints into STRIPE_WEBHOOK_SECRET, then restart the server
```

Check out with card `4242 4242 4242 4242`, then confirm `GET /api/billing/me`
reports `"plan": "cloud"`.

## Endpoints

| Route | Auth | Purpose |
|---|---|---|
| `GET /api/billing/plans` | none | Plan catalogue for the pricing UI |
| `GET /api/billing/me` | user | Plan, limits, usage |
| `POST /api/billing/checkout` | user | → Stripe Checkout URL |
| `POST /api/billing/portal` | user | → Stripe Customer Portal URL |
| `POST /api/billing/webhook` | signature | Provider callbacks |
| `PUT /api/admin/users/{id}/plan` | admin | Comp an account, or clear a comp |

A refused action returns **402** with the numbers the client needs:

```json
{"detail": "…", "code": "quota_exceeded", "resource": "projects",
 "plan": "free", "limit": 1, "used": 1}
```

## How it holds together

- `src/billing/plans.py` — the catalogue and the limits. Pure.
- `src/billing/entitlements.py` — which plan is in force, and the quota checks.
  `plan_from_subscription` is pure; the `ensure_*` helpers raise `QuotaExceeded`,
  which `api/router.py` maps to 402.
- `src/billing/webhook_events.py` — provider event → state. Pure, so every rule
  is tested against recorded payloads with no network.
- `src/billing/subscriptions.py` — applies those updates idempotently. Stripe
  delivers at least once and out of order; a repeated event id is dropped, and
  an event older than the last applied one cannot move state backwards.
- `src/billing/stripe_gateway.py` — the only module that imports the Stripe SDK,
  lazily, so a self-hosted instance never loads it.
- `src/billing/usage.py` — the storage counter. Every photo write adds its bytes
  and every delete subtracts them, because walking the filesystem (what the
  admin dashboard does) is far too slow to put on an upload path. A nightly job
  (03:30 UTC) re-walks each user's tree and corrects any drift.

### Grace and cancellation

`active`, `trialing` and `past_due` all keep the paid plan — a failed renewal
opens a retry window at Stripe, and cutting access off on day one of it loses
customers who only need to update a card. A cancelled subscription keeps the
plan until `current_period_end`: they paid for that time.

An admin comp (`admin_override_plan`) is stored *beside* provider state, not on
top of it, so a webhook can never silently wipe it.

### Deleting an account

Account deletion removes the local subscription and usage rows. It does **not**
cancel anything at Stripe — that record is Stripe's, and must be cancelled
through the dashboard or the customer portal first.

## Not in scope yet

- Apple / Google in-app purchase (the App Store requires IAP for digital goods
  sold inside the iOS app, so mobile currently has no purchase flow).
- Feature gates beyond trip count and storage.
- Dunning and receipt emails (Stripe sends its own for now).
- VAT: we are the merchant of record. Stripe Tax can be switched on when the
  thresholds start to matter.
